import { Component, OnInit, computed, inject, input, output, signal, viewChild } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { FinanceService } from '../core/finance.service';
import { FREQUENCIES, PAYMENT_METHODS, frequencyLabel, moneyToInput, parseMoney, todayIso } from '../core/format';
import { apiMessage } from '../core/http';
import { Account, Category, Kind, Recurrence } from '../core/models';
import { Dialog } from './dialog';

@Component({
  selector: 'app-recurrence-form',
  imports: [ReactiveFormsModule, Dialog],
  template: `
    <app-dialog [heading]="heading()" (closed)="closed.emit()">
      <form [formGroup]="form" (ngSubmit)="save()" novalidate>
        <div class="mb-3">
          <label class="form-label" for="rc-name">Nome</label>
          <input id="rc-name" class="form-control" formControlName="name" maxlength="160"
                 [placeholder]="kind() === 'income' ? 'Salário' : 'Aluguel'" />
        </div>
        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="rc-amount">{{ kind() === 'income' ? 'Valor líquido' : 'Valor' }}</label>
            <input id="rc-amount" class="form-control money" formControlName="amount"
                   inputmode="decimal" placeholder="0,00" autocomplete="off" />
          </div>
          @if (recurrence()) {
            <div>
              <label class="form-label" for="rc-effective">Valor vale a partir de</label>
              <input id="rc-effective" class="form-control" type="month" formControlName="effective_from" [min]="currentMonth" />
            </div>
          } @else {
            <div>
              <label class="form-label" for="rc-frequency">Frequência</label>
              <select id="rc-frequency" class="form-select" formControlName="frequency">
                @for (f of frequencies; track f.value) { <option [value]="f.value">{{ f.label }}</option> }
              </select>
            </div>
          }
        </div>
        @if (recurrence()) {
          <p class="subtle">Meses anteriores e valores já confirmados não mudam.</p>
        }

        <div class="grid-2 mb-3">
          @if (!recurrence()) {
            <div>
              <label class="form-label" for="rc-start">Início</label>
              <input id="rc-start" class="form-control" type="date" formControlName="start_date" />
            </div>
          }
          @if (isMonthly()) {
            <div>
              <label class="form-label" for="rc-day">Dia {{ kind() === 'income' ? 'do recebimento' : 'do vencimento' }}</label>
              <input id="rc-day" class="form-control" type="number" min="1" max="31" formControlName="day_of_month" />
            </div>
          }
          <div>
            <label class="form-label" for="rc-end">Término (opcional)</label>
            <input id="rc-end" class="form-control" type="date" formControlName="end_date" />
          </div>
        </div>

        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="rc-category">Categoria</label>
            <select id="rc-category" class="form-select" formControlName="category_id">
              <option value="">Sem categoria</option>
              @for (c of categories(); track c.id) { <option [value]="c.id">{{ c.name }}</option> }
            </select>
          </div>
          <div>
            <label class="form-label" for="rc-account">Conta</label>
            <select id="rc-account" class="form-select" formControlName="account_id">
              <option value="">Definir depois</option>
              @for (a of accounts(); track a.id) { <option [value]="a.id">{{ a.name }}</option> }
            </select>
          </div>
        </div>

        @if (kind() === 'expense') {
          <div class="mb-3">
            <label class="form-label" for="rc-method">Forma de pagamento</label>
            <select id="rc-method" class="form-select" formControlName="payment_method">
              <option value="">Não informar</option>
              @for (m of methods; track m.value) { <option [value]="m.value">{{ m.label }}</option> }
            </select>
          </div>
        }

        @if (kind() === 'income' && !recurrence()) {
          <div class="form-check mb-3">
            <input id="rc-salary" class="form-check-input" type="checkbox" formControlName="is_salary" />
            <label class="form-check-label" for="rc-salary">Este é meu salário</label>
          </div>
        }

        @if (error()) { <p class="field-error mb-2" role="alert">{{ error() }}</p> }
        <button type="submit" class="btn btn-brand w-100" [disabled]="busy()">
          {{ busy() ? 'Salvando…' : 'Salvar' }}
        </button>
      </form>
    </app-dialog>
  `,
})
export class RecurrenceForm implements OnInit {
  private readonly finance = inject(FinanceService);

  readonly kind = input.required<Kind>();
  readonly recurrence = input<Recurrence | null>(null);
  readonly closed = output<void>();

  private readonly dialog = viewChild.required(Dialog);
  protected readonly frequencies = FREQUENCIES;
  protected readonly methods = PAYMENT_METHODS;
  protected readonly currentMonth = todayIso().slice(0, 7);
  protected readonly accounts = signal<Account[]>([]);
  protected readonly allCategories = signal<Category[]>([]);
  protected readonly categories = computed(() =>
    this.allCategories().filter((c) => c.kind === this.kind()),
  );
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly frequency = signal('monthly');
  protected readonly isMonthly = computed(() => this.frequency() === 'monthly');
  protected readonly heading = computed(() => {
    const rec = this.recurrence();
    if (rec) return `Editar ${rec.name} (${frequencyLabel(rec.frequency).toLowerCase()})`;
    return this.kind() === 'income' ? 'Nova receita recorrente' : 'Nova despesa fixa';
  });

  protected readonly form = new FormGroup({
    name: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
    amount: new FormControl('', { nonNullable: true }),
    effective_from: new FormControl(this.currentMonth, { nonNullable: true }),
    frequency: new FormControl('monthly', { nonNullable: true }),
    start_date: new FormControl(todayIso(), { nonNullable: true }),
    day_of_month: new FormControl<number | null>(Number(todayIso().slice(8))),
    end_date: new FormControl('', { nonNullable: true }),
    category_id: new FormControl('', { nonNullable: true }),
    account_id: new FormControl('', { nonNullable: true }),
    payment_method: new FormControl('', { nonNullable: true }),
    is_salary: new FormControl(false, { nonNullable: true }),
  });

  ngOnInit(): void {
    const rec = this.recurrence();
    this.form.controls.frequency.valueChanges.subscribe((v) => this.frequency.set(v));
    if (rec) {
      this.frequency.set(rec.frequency);
      this.form.patchValue({
        name: rec.name,
        amount: moneyToInput(rec.amount),
        frequency: rec.frequency,
        day_of_month: rec.day_of_month,
        end_date: rec.end_date ?? '',
        category_id: rec.category_id ?? '',
        account_id: rec.account_id ?? '',
        payment_method: rec.payment_method ?? '',
      });
    }
    this.finance.categories().subscribe((c) => this.allCategories.set(c));
    this.finance.accounts().subscribe((all) => {
      const active = all.filter((a) => a.active);
      this.accounts.set(active);
      if (!rec && active.length === 1) this.form.patchValue({ account_id: active[0].id });
    });
  }

  protected save(): void {
    this.error.set(null);
    const value = this.form.getRawValue();
    const amount = parseMoney(value.amount);
    if (!value.name.trim()) {
      this.error.set('Informe o nome.');
      return;
    }
    if (!amount || Number(amount) <= 0) {
      this.error.set('Informe um valor válido, como 89,90.');
      return;
    }

    const shared = {
      name: value.name.trim(),
      amount,
      end_date: value.end_date || null,
      category_id: value.category_id || null,
      account_id: value.account_id || null,
      payment_method: value.payment_method || null,
      ...(this.isMonthly() ? { day_of_month: value.day_of_month } : {}),
    };
    const rec = this.recurrence();
    const request = rec
      ? this.finance.saveRecurrence({ ...shared, effective_from: value.effective_from }, rec.id)
      : this.finance.saveRecurrence({
          ...shared,
          kind: this.kind(),
          frequency: value.frequency,
          start_date: value.start_date,
          is_salary: this.kind() === 'income' && value.is_salary,
        });

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
