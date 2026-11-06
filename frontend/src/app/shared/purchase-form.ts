import { Component, OnInit, computed, inject, input, output, signal, viewChild } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { FinanceService } from '../core/finance.service';
import { parseMoney, todayIso } from '../core/format';
import { apiMessage } from '../core/http';
import { Category, CreditCard } from '../core/models';
import { Dialog } from './dialog';

@Component({
  selector: 'app-purchase-form',
  imports: [ReactiveFormsModule, RouterLink, Dialog],
  template: `
    <app-dialog #dialog heading="Compra no cartão" (closed)="closed.emit()">
      @if (loaded() && !cards().length) {
        <p class="muted">Cadastre um cartão para registrar compras.</p>
        <a class="btn btn-brand w-100" routerLink="/cartoes" (click)="dialog.close()">Ir para Cartões</a>
      } @else {
        <form [formGroup]="form" (ngSubmit)="save()" novalidate>
          <div class="grid-2 mb-3">
            <div>
              <label class="form-label" for="pc-amount">Valor total</label>
              <input id="pc-amount" class="form-control money" formControlName="total_amount"
                     inputmode="decimal" placeholder="0,00" autocomplete="off" />
            </div>
            <div>
              <label class="form-label" for="pc-count">Parcelas</label>
              <input id="pc-count" class="form-control" type="number" min="1" max="48"
                     formControlName="installment_count" />
            </div>
          </div>
          <div class="mb-3">
            <label class="form-label" for="pc-description">Descrição</label>
            <input id="pc-description" class="form-control" formControlName="description" maxlength="160" />
          </div>
          <div class="grid-2 mb-3">
            <div>
              <label class="form-label" for="pc-date">Data da compra</label>
              <input id="pc-date" class="form-control" type="date" formControlName="purchase_date" [max]="today" />
            </div>
            <div>
              <label class="form-label" for="pc-category">Categoria</label>
              <select id="pc-category" class="form-select" formControlName="category_id">
                <option value="">Sem categoria</option>
                @for (c of categories(); track c.id) { <option [value]="c.id">{{ c.name }}</option> }
              </select>
            </div>
          </div>
          @if (!cardId()) {
            <div class="mb-3">
              <label class="form-label" for="pc-card">Cartão</label>
              <select id="pc-card" class="form-select" formControlName="card_id">
                <option value="">Escolha o cartão</option>
                @for (c of cards(); track c.id) { <option [value]="c.id">{{ c.name }}</option> }
              </select>
            </div>
          }

          <details class="mb-3">
            <summary class="subtle">Compra antiga ou outra fatura</summary>
            <div class="grid-2 mt-2">
              <div>
                <label class="form-label" for="pc-paid">Parcelas já pagas</label>
                <input id="pc-paid" class="form-control" type="number" min="0" max="47" formControlName="already_paid" />
              </div>
              <div>
                <label class="form-label" for="pc-first">Primeira fatura a pagar</label>
                <input id="pc-first" class="form-control" type="month" formControlName="first_month" />
              </div>
            </div>
            <p class="subtle mt-2 mb-0">
              Em uma compra parcelada antiga, informe as parcelas já pagas e o mês de vencimento
              da próxima. Sem isso, a fatura é calculada pela data da compra.
            </p>
          </details>

          @if (error()) { <p class="field-error mb-2" role="alert">{{ error() }}</p> }
          <button type="submit" class="btn btn-brand w-100" [disabled]="busy()">
            {{ busy() ? 'Salvando…' : 'Salvar' }}
          </button>
        </form>
      }
    </app-dialog>
  `,
})
export class PurchaseForm implements OnInit {
  private readonly finance = inject(FinanceService);

  /** Vazio no registro rápido: o usuário escolhe o cartão no formulário. */
  readonly cardId = input<string | null>(null);
  readonly closed = output<void>();

  private readonly dialog = viewChild.required(Dialog);
  protected readonly today = todayIso();
  protected readonly cards = signal<CreditCard[]>([]);
  protected readonly loaded = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  private readonly allCategories = toSignal(this.finance.categories(), { initialValue: [] as Category[] });
  protected readonly categories = computed(() =>
    this.allCategories().filter((c) => c.kind === 'expense'),
  );
  private readonly idempotencyKey = crypto.randomUUID();

  protected readonly form = new FormGroup({
    total_amount: new FormControl('', { nonNullable: true }),
    installment_count: new FormControl(1, { nonNullable: true, validators: [Validators.min(1), Validators.max(48)] }),
    description: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
    purchase_date: new FormControl(this.today, { nonNullable: true, validators: [Validators.required] }),
    category_id: new FormControl('', { nonNullable: true }),
    card_id: new FormControl('', { nonNullable: true }),
    already_paid: new FormControl(0, { nonNullable: true }),
    first_month: new FormControl('', { nonNullable: true }),
  });

  ngOnInit(): void {
    this.finance.cards().subscribe((all) => {
      const active = all.filter((c) => c.active);
      this.cards.set(active);
      this.loaded.set(true);
      if (active.length === 1) this.form.patchValue({ card_id: active[0].id });
    });
  }

  protected save(): void {
    if (this.busy()) return;
    this.error.set(null);
    const value = this.form.getRawValue();
    const amount = parseMoney(value.total_amount);
    const cardId = this.cardId() ?? value.card_id;
    if (!amount || Number(amount) <= 0) {
      this.error.set('Informe um valor válido, como 89,90.');
      return;
    }
    if (this.form.invalid) {
      this.error.set('Preencha a descrição, a data e de 1 a 48 parcelas.');
      return;
    }
    if (!cardId) {
      this.error.set('Escolha o cartão.');
      return;
    }
    this.busy.set(true);
    this.finance.createPurchase(cardId, {
      description: value.description.trim(),
      total_amount: amount,
      installment_count: value.installment_count,
      purchase_date: value.purchase_date,
      category_id: value.category_id || null,
      already_paid: value.already_paid || 0,
      first_month: value.first_month || null,
    }, this.idempotencyKey).subscribe({
      next: () => this.dialog().close(),
      error: (e) => {
        this.error.set(apiMessage(e, 'Não foi possível salvar.'));
        this.busy.set(false);
      },
    });
  }
}
