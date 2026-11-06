import { HttpClient } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { AuthService } from '../../core/auth.service';
import { formatMoney, formatMonth, shiftMonth } from '../../core/format';
import { Dashboard, Money } from '../../core/models';
import { HistoryChart } from './history-chart';

interface Kpi {
  label: string;
  value: Money;
  hint: string;
}

@Component({
  selector: 'app-dashboard',
  imports: [HistoryChart],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.css',
})
export class DashboardPage implements OnInit {
  private readonly http = inject(HttpClient);
  protected readonly auth = inject(AuthService);
  private request?: Subscription;

  protected readonly data = signal<Dashboard | null>(null);
  protected readonly failed = signal(false);
  protected readonly loading = signal(true);
  protected readonly money = formatMoney;
  protected readonly monthLabel = computed(() => {
    const d = this.data();
    return d ? formatMonth(d.month) : '';
  });

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
      { label: 'Faturas em aberto', value: s.open_invoices, hint: 'Disponível na Etapa 3' },
      { label: 'Dívidas pendentes', value: s.pending_debts, hint: 'Disponível na Etapa 4' },
      { label: 'Valor economizado', value: s.saved_total, hint: 'Disponível na Etapa 6' },
    ];
  });

  protected readonly maxCategory = computed(() =>
    Math.max(0, ...(this.data()?.by_category ?? []).map((c) => Number(c.total))),
  );

  ngOnInit(): void {
    this.load();
  }

  protected load(month?: string): void {
    this.loading.set(true);
    this.failed.set(false);
    this.request?.unsubscribe();
    this.request = this.http
      .get<Dashboard>('/api/dashboard', { params: month ? { month } : {} })
      .subscribe({
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

  protected go(delta: number): void {
    const current = this.data()?.month;
    if (current) this.load(shiftMonth(current, delta));
  }

  protected barWidth(total: string): number {
    const max = this.maxCategory();
    return max > 0 ? (Number(total) / max) * 100 : 0;
  }
}
