import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { AuthService } from '../../core/auth.service';
import { FinanceService } from '../../core/finance.service';
import { formatMoney, todayIso } from '../../core/format';
import { Dashboard, Money } from '../../core/models';
import { MonthPicker } from '../../shared/month-picker';
import { HistoryChart } from './history-chart';

interface Kpi {
  label: string;
  value: Money;
  hint: string;
}

@Component({
  selector: 'app-dashboard',
  imports: [HistoryChart, MonthPicker, RouterLink],
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
      { label: 'Valor economizado', value: s.saved_total, hint: 'Disponível na Etapa 6' },
    ];
  });

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
