import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { AuthService } from '../../core/auth.service';
import { FinanceService } from '../../core/finance.service';
import { formatMoney, formatMonthShort, todayIso } from '../../core/format';
import { Dashboard, HistoryPoint, Money } from '../../core/models';
import { MonthPicker } from '../../shared/month-picker';
import { TrendChart, TrendSeries } from '../../shared/trend-chart';
import { HistoryChart } from './history-chart';
import { UntilSalaryCard } from './until-salary';

interface Kpi {
  label: string;
  value: Money;
  hint: string;
}

@Component({
  selector: 'app-dashboard',
  imports: [HistoryChart, MonthPicker, RouterLink, TrendChart, UntilSalaryCard],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.css',
})
export class DashboardPage {
  private readonly finance = inject(FinanceService);
  protected readonly auth = inject(AuthService);
  private request?: Subscription;

  protected readonly month = signal(todayIso().slice(0, 7));
  protected readonly data = signal<Dashboard | null>(null);
  protected readonly failed = signal(false);
  protected readonly loading = signal(true);
  protected readonly money = formatMoney;

  protected readonly firstName = computed(
    () => this.auth.user()?.account_name.split(' ')[0] ?? '',
  );

  protected readonly commitmentWidth = computed(() => {
    const pct = this.data()?.summary.income_commitment_pct;
    return pct === null || pct === undefined ? 0 : Math.min(pct, 100);
  });

  protected readonly kpis = computed<Kpi[]>(() => {
    const s = this.data()?.summary;
    if (!s) return [];
    return [
      { label: 'Salário recebido', value: s.salary_received, hint: `${formatMoney(s.salary_expected)} previsto` },
      { label: 'Receitas extras', value: s.extra_income, hint: 'Somente confirmadas' },
      { label: 'Total de despesas', value: s.expenses_total, hint: `${formatMoney(s.expenses_paid)} pagas` },
      { label: 'Despesas pendentes', value: s.expenses_pending, hint: 'Ainda não pagas' },
      { label: 'Gastos no cartão', value: s.card_commitment, hint: 'Parcelas que vencem no mês' },
      { label: 'Faturas em aberto', value: s.open_invoices, hint: 'Falta pagar neste mês' },
      { label: 'Dívidas pendentes', value: s.pending_debts, hint: `${formatMoney(s.debt_payments)} pagos neste mês` },
      { label: 'Valor economizado', value: s.saved_total, hint: 'Guardado para a wishlist' },
    ];
  });

  private readonly history = computed(() => this.data()?.history ?? []);
  protected readonly labels = computed(() => this.history().map((r) => formatMonthShort(r.month)));
  private series(label: string, pick: (r: HistoryPoint) => string | number | null): TrendSeries[] {
    const values = this.history().map((r) => {
      const value = pick(r);
      return value === null ? null : Number(value);
    });
    return [{ label, values, token: '--series-1' }];
  }
  protected readonly balanceSeries = computed(() => this.series('Saldo', (r) => r.balance));
  protected readonly debtSeries = computed(() => this.series('Dívidas', (r) => r.debt_balance));
  protected readonly cardSeries = computed(() => this.series('Cartões', (r) => r.cards));
  protected readonly commitmentSeries = computed(() =>
    this.series('Comprometimento', (r) => r.commitment_pct),
  );
  private readonly maxPart = computed(() =>
    Math.max(0, ...(this.data()?.distribution ?? []).map((d) => Number(d.amount))),
  );

  protected partWidth(amount: string): number {
    const max = this.maxPart();
    return max > 0 ? Math.max(0, (Number(amount) / max) * 100) : 0;
  }

  protected readonly maxCategory = computed(() =>
    Math.max(0, ...(this.data()?.by_category ?? []).map((c) => Number(c.total))),
  );

  constructor() {
    // Recarrega ao trocar o mês ou após qualquer lançamento, inclusive pelo registro rápido.
    effect(() => {
      this.finance.revision();
      const month = this.month();
      untracked(() => this.load(month));
    });
  }

  protected load(month: string): void {
    this.loading.set(true);
    this.failed.set(false);
    this.request?.unsubscribe();
    this.request = this.finance.dashboard(month).subscribe({
      next: (d) => {
        this.data.set(d);
        this.loading.set(false);
      },
      error: () => {
        this.failed.set(true);
        this.loading.set(false);
      },
    });
  }

  protected barWidth(total: string): number {
    const max = this.maxCategory();
    return max > 0 ? (Number(total) / max) * 100 : 0;
  }
}
