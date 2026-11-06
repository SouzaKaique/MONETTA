import { Component, OnInit, inject, input, output, signal, viewChild } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FinanceService } from '../../core/finance.service';
import { moneyToInput, parseMoney, todayIso } from '../../core/format';
import { apiMessage } from '../../core/http';
import { Debt } from '../../core/models';
import { Dialog } from '../../shared/dialog';

@Component({
  selector: 'app-debt-form',
  imports: [ReactiveFormsModule, Dialog],
  template: `
    <app-dialog [heading]="debt() ? 'Editar dívida' : 'Nova dívida'" (closed)="closed.emit()">
      <form [formGroup]="form" (ngSubmit)="save()" novalidate>
        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="db-name">Nome da dívida</label>
            <input id="db-name" class="form-control" formControlName="name" maxlength="120" />
          </div>
          <div>
            <label class="form-label" for="db-creditor">Credor</label>
            <input id="db-creditor" class="form-control" formControlName="creditor" maxlength="120" />
          </div>
        </div>
        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="db-original">Valor original</label>
            <input id="db-original" class="form-control money" formControlName="original_amount"
                   inputmode="decimal" placeholder="0,00" autocomplete="off" />
          </div>
          <div>
            <label class="form-label" for="db-balance">{{ debt() ? 'Saldo ao cadastrar' : 'Saldo hoje (opcional)' }}</label>
            <input id="db-balance" class="form-control money" formControlName="balance"
                   inputmode="decimal" placeholder="Igual ao original" autocomplete="off" />
          </div>
        </div>
        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="db-start">Data da dívida</label>
            <input id="db-start" class="form-control" type="date" formControlName="start_date" />
          </div>
          <div>
            <label class="form-label" for="db-due">Vencimento (opcional)</label>
            <input id="db-due" class="form-control" type="date" formControlName="due_date" />
          </div>
        </div>
        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="db-frequency">Pagamento combinado</label>
            <select id="db-frequency" class="form-select" formControlName="frequency">
              <option value="none">Sem combinado</option>
              <option value="monthly">Mensal</option>
              <option value="biweekly">Quinzenal</option>
              <option value="weekly">Semanal</option>
            </select>
          </div>
          <div>
            <label class="form-label" for="db-agreed">Valor combinado</label>
            <input id="db-agreed" class="form-control money" formControlName="agreed_amount"
                   inputmode="decimal" placeholder="0,00" autocomplete="off" />
          </div>
        </div>
        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="db-rate">Juros ao mês, % (opcional)</label>
            <input id="db-rate" class="form-control money" formControlName="interest_rate"
                   inputmode="decimal" placeholder="Sem juros" autocomplete="off" />
          </div>
          <div>
            <label class="form-label" for="db-priority">Importância</label>
            <select id="db-priority" class="form-select" formControlName="priority">
              <option [ngValue]="1">Alta</option>
              <option [ngValue]="2">Média</option>
              <option [ngValue]="3">Baixa</option>
            </select>
          </div>
        </div>
        <div class="mb-3">
          <label class="form-label" for="db-notes">Observações</label>
          <textarea id="db-notes" class="form-control" rows="2" formControlName="notes" maxlength="2000"></textarea>
        </div>
        @if (error()) { <p class="field-error mb-2" role="alert">{{ error() }}</p> }
        <button type="submit" class="btn btn-brand w-100" [disabled]="busy()">
          {{ busy() ? 'Salvando…' : 'Salvar' }}
        </button>
      </form>
    </app-dialog>
  `,
})
export class DebtForm implements OnInit {
  private readonly finance = inject(FinanceService);

  readonly debt = input<Debt | null>(null);
  readonly closed = output<void>();

  private readonly dialog = viewChild.required(Dialog);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly form = new FormGroup({
    name: new FormControl('', { nonNullable: true }),
    creditor: new FormControl('', { nonNullable: true }),
    original_amount: new FormControl('', { nonNullable: true }),
    balance: new FormControl('', { nonNullable: true }),
    start_date: new FormControl(todayIso(), { nonNullable: true }),
    due_date: new FormControl('', { nonNullable: true }),
    frequency: new FormControl('none', { nonNullable: true }),
    agreed_amount: new FormControl('', { nonNullable: true }),
    interest_rate: new FormControl('', { nonNullable: true }),
    priority: new FormControl(2, { nonNullable: true }),
    notes: new FormControl('', { nonNullable: true }),
  });

  ngOnInit(): void {
    const debt = this.debt();
    if (debt) {
      this.form.patchValue({
        name: debt.name,
        creditor: debt.creditor,
        original_amount: moneyToInput(debt.original_amount),
        balance: moneyToInput(debt.opening_balance),
        start_date: debt.start_date,
        due_date: debt.due_date ?? '',
        frequency: debt.frequency,
        agreed_amount: moneyToInput(debt.agreed_amount),
        interest_rate: debt.interest_rate ? debt.interest_rate.replace(/\.?0+$/, '').replace('.', ',') : '',
        priority: debt.priority,
        notes: debt.notes ?? '',
      });
    }
  }

  /** Campo opcional: vazio vira null; texto inválido vira undefined. */
  private optional(text: string): string | null | undefined {
    if (!text.trim()) return null;
    return parseMoney(text) ?? undefined;
  }

  protected save(): void {
    if (this.busy()) return;
    this.error.set(null);
    const value = this.form.getRawValue();
    const original = parseMoney(value.original_amount);
    const balance = this.optional(value.balance);
    const agreed = this.optional(value.agreed_amount);
    const rate = this.optional(value.interest_rate);
    if (!value.name.trim() || !value.creditor.trim()) {
      this.error.set('Informe o nome da dívida e o credor.');
      return;
    }
    if (!original || Number(original) <= 0 || balance === undefined || agreed === undefined || rate === undefined) {
      this.error.set('Confira os valores informados, como 1.500,00.');
      return;
    }

    const shared = {
      name: value.name.trim(),
      creditor: value.creditor.trim(),
      original_amount: original,
      start_date: value.start_date,
      due_date: value.due_date || null,
      frequency: value.frequency,
      agreed_amount: agreed,
      interest_rate: rate,
      priority: value.priority,
      notes: value.notes || null,
    };
    const debt = this.debt();
    const request = debt
      ? this.finance.saveDebt({ ...shared, opening_balance: balance ?? original }, debt.id)
      : this.finance.saveDebt({ ...shared, current_balance: balance });

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
