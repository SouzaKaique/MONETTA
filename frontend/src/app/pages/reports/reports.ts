import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { FinanceService } from '../../core/finance.service';
import { formatDate, formatMoney, formatMonth, formatMonthShort, shiftMonth, todayIso } from '../../core/format';
import { apiMessage } from '../../core/http';
import { Report, ReportPeriod } from '../../core/models';
import { TrendChart, TrendSeries } from '../../shared/trend-chart';

const STEP: Record<ReportPeriod, number> = { month: 1, quarter: 3, year: 12 };

@Component({
  selector: 'app-reports',
  imports: [TrendChart],
  templateUrl: './reports.html',
  styleUrl: './reports.css',
})
export class ReportsPage {
  private readonly finance = inject(FinanceService);

  protected readonly periods: { value: ReportPeriod; label: string }[] = [
    { value: 'month', label: 'Mês' }, { value: 'quarter', label: 'Trimestre' }, { value: 'year', label: 'Ano' },
  ];
  protected readonly downloads = [
    { key: 'lancamentos', label: 'Lançamentos', period: true },
    { key: 'compras-cartao', label: 'Compras no cartão', period: true },
    { key: 'faturas', label: 'Faturas', period: true },
    { key: 'pagamentos-dividas', label: 'Pagamentos de dívidas', period: true },
    { key: 'transferencias', label: 'Transferências', period: true },
    { key: 'dividas', label: 'Dívidas', period: false },
    { key: 'wishlist', label: 'Wishlist', period: false },
  ];
  protected readonly money = formatMoney;
  protected readonly date = formatDate;

  protected readonly period = signal<ReportPeriod>('month');
  protected readonly month = signal(todayIso().slice(0, 7));
  protected readonly data = signal<Report | null>(null);
  protected readonly error = signal<string | null>(null);

  protected readonly label = computed(() => {
    const [year, month] = this.month().split('-').map(Number);
    if (this.period() === 'year') return String(year);
    if (this.period() === 'quarter') return `${Math.floor((month - 1) / 3) + 1}º trimestre de ${year}`;
    return formatMonth(this.month());
  });

  private readonly evolution = computed(() => this.data()?.evolution ?? []);
  protected readonly labels = computed(() => this.evolution().map((r) => formatMonthShort(r.month)));

  private number(pick: (row: Report['evolution'][number]) => string | number | null): (number | null)[] {
    return this.evolution().map((row) => {
      const value = pick(row);
      return value === null ? null : Number(value);
    });
  }

  protected readonly flow = computed<TrendSeries[]>(() => [
    { label: 'Receitas', values: this.number((r) => r.income), token: '--series-1' },
    { label: 'Despesas', values: this.number((r) => r.expenses), token: '--series-2' },
  ]);
  protected readonly balance = computed<TrendSeries[]>(() => [
    { label: 'Saldo', values: this.number((r) => r.balance), token: '--series-1' },
  ]);
  protected readonly debts = computed<TrendSeries[]>(() => [
    { label: 'Dívidas', values: this.number((r) => r.debt_balance), token: '--series-1' },
  ]);
  protected readonly cards = computed<TrendSeries[]>(() => [
    { label: 'Cartões', values: this.number((r) => r.cards), token: '--series-1' },
  ]);
  protected readonly savings = computed<TrendSeries[]>(() => [
    { label: 'Economia', values: this.number((r) => r.savings_pct), token: '--series-1' },
  ]);

  private readonly maxCategory = computed(() =>
    Math.max(0, ...(this.data()?.categories ?? []).map((c) => Number(c.total))),
  );
  private readonly maxPart = computed(() =>
    Math.max(0, ...(this.data()?.distribution ?? []).map((d) => Number(d.amount))),
  );

  constructor() {
    effect(() => {
      this.finance.revision();
      const period = this.period();
      const month = this.month();
      untracked(() => this.finance.report(period, month).subscribe({
        next: (r) => {
          this.error.set(null);
          this.data.set(r);
        },
        error: (e) => this.error.set(apiMessage(e, 'Não foi possível carregar o relatório.')),
      }));
    });
  }

  protected go(direction: number): void {
    this.month.set(shiftMonth(this.month(), direction * STEP[this.period()]));
  }

  protected categoryWidth(total: string): number {
    const max = this.maxCategory();
    return max > 0 ? (Number(total) / max) * 100 : 0;
  }

  protected partWidth(amount: string): number {
    const max = this.maxPart();
    return max > 0 ? Math.max(0, (Number(amount) / max) * 100) : 0;
  }

  protected exportUrl(key: string, usePeriod: boolean): string {
    const d = this.data();
    const range = usePeriod && d ? `?from=${d.start}&to=${d.end}` : '';
    return `/api/export/${key}.csv${range}`;
  }
}
