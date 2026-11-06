import { Component, OnInit, computed, inject, input, output, signal, viewChild } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FinanceService } from '../../core/finance.service';
import { moneyToInput, parseMoney, todayIso } from '../../core/format';
import { apiMessage } from '../../core/http';
import { Account, Debt } from '../../core/models';
import { Dialog } from '../../shared/dialog';

@Component({
  selector: 'app-debt-payment-form',
  imports: [ReactiveFormsModule, Dialog],
  template: `
    <app-dialog [heading]="heading()" (closed)="closed.emit()">
      <p class="subtle">O pagamento reduz a dívida e não conta como despesa.</p>
      <form [formGroup]="form" (ngSubmit)="save()" novalidate>
        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="dp-amount">Valor</label>
            <input id="dp-amount" class="form-control money" formControlName="amount" inputmode="decimal" autocomplete="off" />
          </div>
          <div>
            <label class="form-label" for="dp-date">Data</label>
            <input id="dp-date" class="form-control" type="date" formControlName="paid_on" [max]="today" />
          </div>
        </div>
        <div class="mb-3">
          <label class="form-label" for="dp-account">Saiu de qual conta?</label>
          <select id="dp-account" class="form-select" formControlName="account_id">
            <option value="">Não saiu de uma conta cadastrada</option>
            @for (a of accounts(); track a.id) { <option [value]="a.id">{{ a.name }}</option> }
          </select>
          <div class="subtle mt-1">Use a segunda opção para pagamentos antigos: o saldo de hoje não muda.</div>
        </div>
        <div class="mb-3">
          <label class="form-label" for="dp-description">Descrição (opcional)</label>
          <input id="dp-description" class="form-control" formControlName="description" maxlength="160" />
        </div>
        <div class="mb-3">
          <label class="form-label" for="dp-notes">Observações (opcional)</label>
          <textarea id="dp-notes" class="form-control" rows="2" formControlName="notes" maxlength="2000"></textarea>
        </div>
        @if (error()) { <p class="field-error mb-2" role="alert">{{ error() }}</p> }
        <button type="submit" class="btn btn-brand w-100" [disabled]="busy()">Registrar pagamento</button>
      </form>
    </app-dialog>
  `,
})
export class DebtPaymentForm implements OnInit {
  private readonly finance = inject(FinanceService);

  readonly debt = input.required<Debt>();
  readonly closed = output<void>();

  private readonly dialog = viewChild.required(Dialog);
  protected readonly today = todayIso();
  protected readonly accounts = signal<Account[]>([]);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly heading = computed(() => `Pagamento: ${this.debt().name}`);
  private readonly idempotencyKey = crypto.randomUUID();

  protected readonly form = new FormGroup({
    amount: new FormControl('', { nonNullable: true }),
    paid_on: new FormControl(this.today, { nonNullable: true }),
    account_id: new FormControl('', { nonNullable: true }),
    description: new FormControl('', { nonNullable: true }),
    notes: new FormControl('', { nonNullable: true }),
  });

  ngOnInit(): void {
    const debt = this.debt();
    const suggestion = debt.agreed_amount && Number(debt.agreed_amount) < Number(debt.balance)
      ? debt.agreed_amount : debt.balance;
    this.form.patchValue({ amount: moneyToInput(suggestion) });
    this.finance.accounts().subscribe((all) => {
      const active = all.filter((a) => a.active);
      this.accounts.set(active);
      if (active.length === 1) this.form.patchValue({ account_id: active[0].id });
    });
  }

  protected save(): void {
    if (this.busy()) return;
    this.error.set(null);
    const value = this.form.getRawValue();
    const amount = parseMoney(value.amount);
    if (!amount || Number(amount) <= 0) {
      this.error.set('Informe um valor válido, como 89,90.');
      return;
    }
    this.busy.set(true);
    this.finance.payDebt(this.debt().id, {
      amount,
      paid_on: value.paid_on,
      account_id: value.account_id || null,
      description: value.description || null,
      notes: value.notes || null,
    }, this.idempotencyKey).subscribe({
      next: () => this.dialog().close(),
      error: (e) => {
        this.error.set(apiMessage(e, 'Não foi possível registrar o pagamento.'));
        this.busy.set(false);
      },
    });
  }
}
