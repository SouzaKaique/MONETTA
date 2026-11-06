import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { FinanceService } from '../../core/finance.service';
import { formatMoney, todayIso } from '../../core/format';
import { DashboardSummary, Money, Transaction } from '../../core/models';
import { MonthPicker } from '../../shared/month-picker';
import { RecurrenceList } from '../../shared/recurrence-list';
import { TransactionForm } from '../../shared/transaction-form';
import { TransactionRows } from '../../shared/transaction-rows';

@Component({
  selector: 'app-income',
  imports: [MonthPicker, RecurrenceList, TransactionForm, TransactionRows],
  template: `
    <header class="page-head">
      <div>
        <h1 class="page-title">Receitas</h1>
        <p class="muted mb-0">O que você espera receber e o que já entrou.</p>
      </div>
      <app-month-picker [month]="month()" (monthChange)="month.set($event)" />
    </header>

    @if (failed()) {
      <div class="notice notice-critical mt-3" role="alert">
        <i class="bi bi-exclamation-circle" aria-hidden="true"></i>
        <span>Não foi possível carregar as receitas.</span>
      </div>
    }

    <section class="stat-grid" aria-label="Distribuição da renda">
      @for (stat of stats(); track stat.label) {
        <article class="card-m stat" [class.pending]="stat.value === null">
          <h2>{{ stat.label }}</h2>
          <p class="money">{{ money(stat.value) }}</p>
          @if (stat.hint) { <small>{{ stat.hint }}</small> }
        </article>
      }
    </section>

    <section class="card-m mt-3"><app-recurrence-list kind="income" /></section>

    <section class="card-m mt-3">
      <div class="section-head">
        <h2 class="card-title-m">Entradas do mês</h2>
        <button type="button" class="btn btn-quiet btn-sm" (click)="creating.set(true)">
          <i class="bi bi-plus-lg me-1" aria-hidden="true"></i>Receita extra
        </button>
      </div>
      @if (entries().length) {
        <app-transaction-rows [items]="entries()" />
      } @else if (!loading()) {
        <p class="subtle mb-0">Nenhuma entrada neste mês.</p>
      }
    </section>

    @if (creating()) {
      <app-transaction-form kind="income" (closed)="creating.set(false)" />
    }
  `,
})
export class IncomePage {
  private readonly finance = inject(FinanceService);

  protected readonly month = signal(todayIso().slice(0, 7));
  protected readonly summary = signal<DashboardSummary | null>(null);
  protected readonly entries = signal<Transaction[]>([]);
  protected readonly loading = signal(true);
  protected readonly failed = signal(false);
  protected readonly creating = signal(false);
  protected readonly money = formatMoney;

  protected readonly stats = computed<{ label: string; value: Money; hint?: string }[]>(() => {
    const s = this.summary();
    if (!s) return [];
    return [
      { label: 'Renda prevista', value: s.income_expected },
      { label: 'Renda recebida', value: s.income_received },
      { label: 'Despesas fixas', value: s.expenses_fixed },
      { label: 'Despesas variáveis', value: s.expenses_variable },
      { label: 'Dinheiro livre', value: s.free_money, hint: 'Renda prevista menos despesas e dívidas' },
      { label: 'Cartões', value: s.card_commitment, hint: 'Parcelas que vencem no mês' },
      { label: 'Dívidas', value: s.debt_payments, hint: `Faltam ${formatMoney(s.debt_due)} do combinado` },
      { label: 'Reservas', value: s.reserves, hint: 'Disponível na Etapa 6' },
    ];
  });

  constructor() {
    effect(() => {
      this.finance.revision();
      const month = this.month();
      untracked(() => this.load(month));
    });
  }

  private load(month: string): void {
    this.loading.set(true);
    this.failed.set(false);
    const fail = () => {
      this.failed.set(true);
      this.loading.set(false);
    };
    this.finance.dashboard(month).subscribe({ next: (d) => this.summary.set(d.summary), error: fail });
    this.finance.transactions({ month, kind: 'income' }).subscribe({
      next: (page) => {
        this.entries.set(page.items);
        this.loading.set(false);
      },
      error: fail,
    });
  }
}
