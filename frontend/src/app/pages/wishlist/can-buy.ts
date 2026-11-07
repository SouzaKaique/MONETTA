import { Component, OnInit, inject, input, output, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FinanceService } from '../../core/finance.service';
import { formatMoney, moneyToInput, parseMoney } from '../../core/format';
import { apiMessage } from '../../core/http';
import { CreditCard, PurchaseAdvice, WishlistItem } from '../../core/models';
import { Dialog } from '../../shared/dialog';

const ICONS = { ok: 'bi-check-circle', warning: 'bi-exclamation-circle', bad: 'bi-x-circle' };

/** Análise "Posso comprar?": recomenda, explica e nunca impede a compra. */
@Component({
  selector: 'app-can-buy',
  imports: [ReactiveFormsModule, Dialog],
  template: `
    <app-dialog heading="Posso comprar?" (closed)="closed.emit()">
      @if (item(); as it) { <p class="muted">{{ it.name }}</p> }
      <form [formGroup]="form" (ngSubmit)="analyze()" novalidate>
        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="cb-amount">Valor</label>
            <input id="cb-amount" class="form-control money" formControlName="amount"
                   inputmode="decimal" placeholder="0,00" autocomplete="off" />
          </div>
          <div>
            <label class="form-label" for="cb-card">Pagamento</label>
            <select id="cb-card" class="form-select" formControlName="card_id">
              <option value="">À vista</option>
              @for (c of cards(); track c.id) { <option [value]="c.id">{{ c.name }}</option> }
            </select>
          </div>
          @if (form.controls.card_id.value) {
            <div>
              <label class="form-label" for="cb-installments">Parcelas</label>
              <input id="cb-installments" class="form-control" type="number" min="1" max="48"
                     formControlName="installments" />
            </div>
          }
        </div>
        @if (error()) { <p class="field-error mb-2" role="alert">{{ error() }}</p> }
        <button type="submit" class="btn btn-quiet w-100" [disabled]="busy()">Analisar</button>
      </form>

      @if (result(); as r) {
        <div class="verdict verdict-{{ r.verdict }} fade-up" role="status">
          <strong>{{ r.message }}</strong>
          @if (r.saved !== '0.00') {
            <small>{{ money(r.saved) }} já guardados · faltam {{ money(r.need) }}</small>
          }
        </div>
        <ul class="checks">
          @for (c of r.checks; track c.label) {
            <li>
              <i class="bi {{ icons[c.status] }} status-{{ c.status }}" aria-hidden="true"></i>
              <span><strong>{{ c.label }}</strong><small>{{ c.detail }}</small></span>
            </li>
          }
        </ul>
        <p class="subtle mb-0">É uma recomendação. A decisão é sua.</p>
      }
    </app-dialog>
  `,
  styles: `
    .verdict { border-radius: var(--radius-sm); display: flex; flex-direction: column; margin-top: 1rem; padding: 0.7rem 0.85rem; }
    .verdict strong { font-weight: 600; }
    .verdict small { opacity: 0.85; }
    .verdict-buy { background: var(--accent-soft); color: var(--accent); }
    .verdict-attention { background: var(--warning-soft); color: var(--warning); }
    .verdict-postpone { background: var(--negative-soft); color: var(--negative); }
    .checks { display: grid; gap: 0.5rem; list-style: none; margin: 0.75rem 0; padding: 0; }
    .checks li { display: flex; gap: 0.5rem; }
    .checks span { display: flex; flex-direction: column; font-size: 0.875rem; }
    .checks strong { font-weight: 500; }
    .checks small { color: var(--ink-2); }
    .status-ok { color: var(--accent); }
    .status-warning { color: var(--warning); }
    .status-bad { color: var(--negative); }
  `,
})
export class CanBuy implements OnInit {
  private readonly finance = inject(FinanceService);

  /** Vazio analisa uma compra avulsa, fora da wishlist. */
  readonly item = input<WishlistItem | null>(null);
  readonly closed = output<void>();

  protected readonly icons = ICONS;
  protected readonly money = formatMoney;
  protected readonly cards = signal<CreditCard[]>([]);
  protected readonly result = signal<PurchaseAdvice | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly form = new FormGroup({
    amount: new FormControl('', { nonNullable: true }),
    card_id: new FormControl('', { nonNullable: true }),
    installments: new FormControl(1, { nonNullable: true }),
  });

  ngOnInit(): void {
    const item = this.item();
    if (item) this.form.patchValue({ amount: moneyToInput(item.price) });
    this.finance.cards().subscribe((all) => this.cards.set(all.filter((c) => c.active)));
    if (item) this.analyze();
  }

  protected analyze(): void {
    this.error.set(null);
    const value = this.form.getRawValue();
    const amount = parseMoney(value.amount);
    if (!amount || Number(amount) <= 0) {
      this.error.set('Informe um valor válido, como 500,00.');
      return;
    }
    this.busy.set(true);
    this.finance.canBuy({
      amount,
      item_id: this.item()?.id ?? null,
      card_id: value.card_id || null,
      installments: value.card_id ? value.installments || 1 : 1,
    }).subscribe({
      next: (r) => {
        this.result.set(r);
        this.busy.set(false);
      },
      error: (e) => {
        this.error.set(apiMessage(e, 'Não foi possível analisar.'));
        this.busy.set(false);
      },
    });
  }
}
