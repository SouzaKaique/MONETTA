import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { FinanceService } from '../../core/finance.service';
import { formatDate, formatMoney, formatMonth, formatMonthShort, moneyToInput, parseMoney } from '../../core/format';
import { apiMessage } from '../../core/http';
import { Debt, DebtStrategy, Recovery, RecoveryImpact } from '../../core/models';
import { DebtSimulator } from '../debts/debt-simulator';

@Component({
  selector: 'app-recovery',
  imports: [ReactiveFormsModule, RouterLink, DebtSimulator],
  templateUrl: './recovery.html',
  styleUrl: './recovery.css',
})
export class RecoveryPage {
  private readonly finance = inject(FinanceService);

  protected readonly strategies: { value: DebtStrategy; label: string }[] = [
    { value: 'snowball', label: 'Bola de neve' },
    { value: 'avalanche', label: 'Avalanche' },
    { value: 'due_date', label: 'Vencimento' },
    { value: 'priority', label: 'Importância' },
    { value: 'custom', label: 'Minha ordem' },
  ];
  protected readonly money = formatMoney;
  protected readonly date = formatDate;
  protected readonly monthLabel = formatMonth;
  protected readonly monthShort = formatMonthShort;

  protected readonly data = signal<Recovery | null>(null);
  protected readonly debts = signal<Debt[]>([]);
  protected readonly priority = signal<string[]>([]);
  protected readonly configuring = signal(false);
  protected readonly confirmingOff = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly formError = signal<string | null>(null);
  protected readonly impact = signal<RecoveryImpact | null>(null);

  protected readonly activeDebts = computed(() => this.debts().filter((d) => d.status !== 'paid'));
  protected readonly maxEvolution = computed(() =>
    Math.max(0, ...(this.data()?.status?.evolution ?? []).map((e) => Number(e.balance))),
  );
  protected readonly limitOver = computed(() => {
    const n = this.data()?.status?.non_essential;
    return !!n?.limit && Number(n.spent) > Number(n.limit);
  });

  protected readonly form = new FormGroup({
    monthly_amount: new FormControl('', { nonNullable: true }),
    strategy: new FormControl<DebtStrategy>('snowball', { nonNullable: true }),
    non_essential_limit: new FormControl('', { nonNullable: true }),
    reserve_minimum: new FormControl('', { nonNullable: true }),
    spending_goal_pct: new FormControl<number | null>(null),
    target_date: new FormControl('', { nonNullable: true }),
  });
  protected readonly impactAmount = new FormControl('', { nonNullable: true });

  constructor() {
    effect(() => {
      this.finance.revision();
      untracked(() => this.load());
    });
  }

  private load(): void {
    const fail = (e: unknown) => this.error.set(apiMessage(e, 'Não foi possível carregar.'));
    this.finance.recovery().subscribe({ next: (r) => this.data.set(r), error: fail });
    this.finance.debts().subscribe({ next: (d) => this.debts.set(d.items), error: fail });
  }

  protected evolutionWidth(balance: string): number {
    const max = this.maxEvolution();
    return max > 0 ? (Number(balance) / max) * 100 : 0;
  }

  protected openConfig(): void {
    const config = this.data()?.config;
    this.formError.set(null);
    this.priority.set(config?.priority_debt_ids ?? []);
    this.form.reset({
      monthly_amount: moneyToInput(config?.monthly_amount),
      strategy: config?.strategy ?? 'snowball',
      non_essential_limit: moneyToInput(config?.non_essential_limit),
      reserve_minimum: moneyToInput(config?.reserve_minimum === '0.00' ? null : config?.reserve_minimum),
      spending_goal_pct: config?.spending_goal_pct ?? null,
      target_date: config?.target_date ?? '',
    });
    this.configuring.set(true);
  }

  protected togglePriority(id: string): void {
    this.priority.update((all) => (all.includes(id) ? all.filter((i) => i !== id) : [...all, id]));
  }

  protected save(): void {
    if (this.busy()) return;
    this.formError.set(null);
    const value = this.form.getRawValue();
    const monthly = parseMoney(value.monthly_amount);
    const limit = value.non_essential_limit.trim() ? parseMoney(value.non_essential_limit) : '';
    const reserve = value.reserve_minimum.trim() ? parseMoney(value.reserve_minimum) : '0';
    if (!monthly || Number(monthly) <= 0) {
      this.formError.set('Informe o valor mensal para as dívidas.');
      return;
    }
    if (limit === null || reserve === null) {
      this.formError.set('Confira os valores informados, como 500,00.');
      return;
    }
    this.busy.set(true);
    this.finance.saveRecovery({
      monthly_amount: monthly,
      strategy: value.strategy,
      priority_debt_ids: this.priority(),
      non_essential_limit: limit || null,
      reserve_minimum: reserve,
      spending_goal_pct: value.spending_goal_pct || null,
      target_date: value.target_date || null,
    }).subscribe({
      next: () => {
        this.busy.set(false);
        this.configuring.set(false);
      },
      error: (e) => {
        this.busy.set(false);
        this.formError.set(apiMessage(e, 'Não foi possível salvar.'));
      },
    });
  }

  protected deactivate(): void {
    this.finance.deactivateRecovery().subscribe({
      next: () => this.confirmingOff.set(false),
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível desativar.')),
    });
  }

  protected simulateImpact(): void {
    const amount = parseMoney(this.impactAmount.value);
    if (!amount || Number(amount) <= 0) {
      this.impact.set(null);
      return;
    }
    this.finance.recoveryImpact(amount).subscribe({
      next: (r) => this.impact.set(r),
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível calcular.')),
    });
  }
}
