import { Component, OnInit, computed, inject, input, output, signal, viewChild } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FinanceService } from '../core/finance.service';
import { moneyToInput, parseMoney, todayIso } from '../core/format';
import { apiMessage } from '../core/http';
import { Account, Transaction } from '../core/models';
import { Dialog } from './dialog';

/** Confirma que o dinheiro entrou ou saiu; só aqui um lançamento pendente afeta o saldo. */
@Component({
  selector: 'app-confirm-form',
  imports: [ReactiveFormsModule, Dialog],
  template: `
    <app-dialog [heading]="heading()" (closed)="closed.emit()">
      <p class="muted">{{ transaction().description }}</p>
      <form [formGroup]="form" (ngSubmit)="save()" novalidate>
        <div class="mb-3">
          <label class="form-label" for="cf-amount">Valor</label>
          <input id="cf-amount" class="form-control money" formControlName="amount" inputmode="decimal" />
        </div>
        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="cf-date">Data</label>
            <input id="cf-date" class="form-control" type="date" formControlName="paid_on" [max]="today" />
          </div>
          <div>
            <label class="form-label" for="cf-account">Conta</label>
            <select id="cf-account" class="form-select" formControlName="account_id">
              <option value="">Escolha a conta</option>
              @for (a of accounts(); track a.id) { <option [value]="a.id">{{ a.name }}</option> }
            </select>
          </div>
        </div>
        @if (error()) { <p class="field-error mb-2" role="alert">{{ error() }}</p> }
        <button type="submit" class="btn btn-brand w-100" [disabled]="busy()">Confirmar</button>
      </form>
    </app-dialog>
  `,
})
export class ConfirmForm implements OnInit {
  private readonly finance = inject(FinanceService);

  readonly transaction = input.required<Transaction>();
  readonly closed = output<void>();

  private readonly dialog = viewChild.required(Dialog);
  protected readonly today = todayIso();
  protected readonly accounts = signal<Account[]>([]);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly heading = computed(() =>
    this.transaction().kind === 'income' ? 'Confirmar recebimento' : 'Confirmar pagamento',
  );

  protected readonly form = new FormGroup({
    amount: new FormControl('', { nonNullable: true }),
    paid_on: new FormControl(this.today, { nonNullable: true }),
    account_id: new FormControl('', { nonNullable: true }),
  });

  ngOnInit(): void {
    const tx = this.transaction();
    this.form.patchValue({ amount: moneyToInput(tx.amount), account_id: tx.account_id ?? '' });
    if (tx.competence_date < this.today) this.form.patchValue({ paid_on: tx.competence_date });
    this.finance.accounts().subscribe((all) => {
      const active = all.filter((a) => a.active);
      this.accounts.set(active);
      if (!tx.account_id && active.length === 1) this.form.patchValue({ account_id: active[0].id });
    });
  }

  protected save(): void {
    if (this.busy()) return;
    const value = this.form.getRawValue();
    const amount = parseMoney(value.amount);
    if (!amount || Number(amount) <= 0) {
      this.error.set('Informe um valor válido, como 89,90.');
      return;
    }
    if (!value.account_id) {
      this.error.set('Escolha a conta.');
      return;
    }
    this.busy.set(true);
    this.finance.confirmTransaction(this.transaction().id, { ...value, amount }).subscribe({
      next: () => this.dialog().close(),
      error: (e) => {
        this.error.set(apiMessage(e, 'Não foi possível confirmar.'));
        this.busy.set(false);
      },
    });
  }
}
