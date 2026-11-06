import { Component, OnInit, computed, inject, input, output, signal, viewChild } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { FinanceService } from '../core/finance.service';
import { PAYMENT_METHODS, moneyToInput, parseMoney, todayIso } from '../core/format';
import { apiMessage } from '../core/http';
import { Account, Category, Kind, Transaction } from '../core/models';
import { Dialog } from './dialog';

@Component({
  selector: 'app-transaction-form',
  imports: [ReactiveFormsModule, RouterLink, Dialog],
  template: `
    <app-dialog #dialog [heading]="heading()" (closed)="closed.emit()">
      <form [formGroup]="form" (ngSubmit)="save()" novalidate>
        <div class="mb-3">
          <label class="form-label" for="tx-amount">Valor</label>
          <input id="tx-amount" class="form-control money" formControlName="amount"
                 inputmode="decimal" placeholder="0,00" autocomplete="off" />
        </div>
        <div class="mb-3">
          <label class="form-label" for="tx-description">Descrição</label>
          <input id="tx-description" class="form-control" formControlName="description" maxlength="160" />
        </div>
        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="tx-date">Data</label>
            <input id="tx-date" class="form-control" type="date" formControlName="competence_date" />
          </div>
          <div>
            <label class="form-label" for="tx-category">Categoria</label>
            <select id="tx-category" class="form-select" formControlName="category_id">
              <option value="">Sem categoria</option>
              @for (c of categories(); track c.id) { <option [value]="c.id">{{ c.name }}</option> }
            </select>
          </div>
        </div>

        @if (!transaction()) {
          <div class="segmented mb-3" role="group" aria-label="Situação">
            <button type="button" [class.active]="paid()" (click)="setPaid(true)">{{ paidLabel() }}</button>
            <button type="button" [class.active]="!paid()" (click)="setPaid(false)">Pendente</button>
          </div>
        }

        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="tx-account">Conta</label>
            <select id="tx-account" class="form-select" formControlName="account_id">
              <option value="">{{ paid() ? 'Escolha a conta' : 'Definir depois' }}</option>
              @for (a of accounts(); track a.id) { <option [value]="a.id">{{ a.name }}</option> }
            </select>
          </div>
          <div>
            <label class="form-label" for="tx-method">Forma de pagamento</label>
            <select id="tx-method" class="form-select" formControlName="payment_method">
              <option value="">Não informar</option>
              @for (m of methods; track m.value) { <option [value]="m.value">{{ m.label }}</option> }
            </select>
          </div>
        </div>
        @if (loaded() && !accounts().length) {
          <p class="subtle">Cadastre uma conta em
            <a routerLink="/configuracoes" (click)="dialog.close()">Configurações</a>
            para registrar lançamentos pagos.</p>
        }

        <div class="mb-3">
          <label class="form-label" for="tx-notes">Observações</label>
          <textarea id="tx-notes" class="form-control" rows="2" formControlName="notes" maxlength="2000"></textarea>
        </div>

        @if (error()) { <p class="field-error mb-2" role="alert">{{ error() }}</p> }
        <button type="submit" class="btn btn-brand w-100" [disabled]="busy()">
          {{ busy() ? 'Salvando…' : 'Salvar' }}
        </button>
      </form>
    </app-dialog>
  `,
})
export class TransactionForm implements OnInit {
  private readonly finance = inject(FinanceService);

  readonly kind = input.required<Kind>();
  readonly transaction = input<Transaction | null>(null);
  readonly closed = output<void>();

  private readonly dialog = viewChild.required(Dialog);
  protected readonly methods = PAYMENT_METHODS;
  protected readonly paid = signal(true);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly loaded = signal(false);
  protected readonly accounts = signal<Account[]>([]);
  private readonly allCategories = toSignal(this.finance.categories(), { initialValue: [] as Category[] });
  protected readonly categories = computed(() =>
    this.allCategories().filter((c) => c.kind === this.kind()),
  );
  // Fica igual em todas as tentativas de envio deste formulário.
  private readonly idempotencyKey = crypto.randomUUID();

  protected readonly heading = computed(() => {
    const noun = this.kind() === 'income' ? 'receita' : 'despesa';
    return this.transaction() ? `Editar ${noun}` : `Nova ${noun}`;
  });
  protected readonly paidLabel = computed(() => (this.kind() === 'income' ? 'Recebida' : 'Paga'));

  protected readonly form = new FormGroup({
    amount: new FormControl('', { nonNullable: true }),
    description: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
    competence_date: new FormControl(todayIso(), { nonNullable: true, validators: [Validators.required] }),
    category_id: new FormControl('', { nonNullable: true }),
    account_id: new FormControl('', { nonNullable: true }),
    payment_method: new FormControl('', { nonNullable: true }),
    notes: new FormControl('', { nonNullable: true }),
  });

  ngOnInit(): void {
    const tx = this.transaction();
    if (tx) {
      this.paid.set(tx.status === 'confirmed');
      this.form.patchValue({
        amount: moneyToInput(tx.amount),
        description: tx.description,
        competence_date: tx.competence_date,
        category_id: tx.category_id ?? '',
        account_id: tx.account_id ?? '',
        payment_method: tx.payment_method ?? '',
        notes: tx.notes ?? '',
      });
    }
    this.finance.accounts().subscribe((all) => {
      const usable = all.filter((a) => a.active || a.id === tx?.account_id);
      this.accounts.set(usable);
      this.loaded.set(true);
      if (!tx && usable.length === 1) this.form.controls.account_id.setValue(usable[0].id);
    });
  }

  protected setPaid(value: boolean): void {
    this.paid.set(value);
  }

  protected save(): void {
    this.error.set(null);
    const amount = parseMoney(this.form.controls.amount.value);
    if (!amount || Number(amount) <= 0) {
      this.error.set('Informe um valor válido, como 89,90.');
      return;
    }
    if (this.form.invalid) {
      this.error.set('Preencha a descrição e a data.');
      return;
    }

    const value = this.form.getRawValue();
    const fields = {
      amount,
      description: value.description.trim(),
      competence_date: value.competence_date,
      category_id: value.category_id || null,
      account_id: value.account_id || null,
      payment_method: value.payment_method || null,
      notes: value.notes || null,
    };
    const tx = this.transaction();
    const request = tx
      ? this.finance.updateTransaction(tx.id, tx.status === 'confirmed'
          ? { ...fields, paid_on: tx.paid_on } : fields)
      : this.finance.createTransaction(
          { ...fields, kind: this.kind(), status: this.paid() ? 'confirmed' : 'pending' },
          this.idempotencyKey,
        );

    this.busy.set(true);
    request.subscribe({
      next: () => this.dialog().close(),
      error: (e) => {
        this.error.set(apiMessage(e, 'Não foi possível salvar.'));
        this.busy.set(false);
      },
    });
  }
}
