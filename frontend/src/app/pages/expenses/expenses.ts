import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { Subscription, debounceTime } from 'rxjs';
import { toSignal } from '@angular/core/rxjs-interop';
import { FinanceService } from '../../core/finance.service';
import { formatMoney, parseMoney, todayIso } from '../../core/format';
import { Account, Category, DashboardSummary, TransactionPage } from '../../core/models';
import { MonthPicker } from '../../shared/month-picker';
import { RecurrenceList } from '../../shared/recurrence-list';
import { TransactionForm } from '../../shared/transaction-form';
import { TransactionRows } from '../../shared/transaction-rows';

@Component({
  selector: 'app-expenses',
  imports: [ReactiveFormsModule, MonthPicker, RecurrenceList, TransactionForm, TransactionRows],
  template: `
    <header class="page-head">
      <div>
        <h1 class="page-title">Despesas</h1>
        <p class="muted mb-0">Tudo o que saiu e o que ainda vai sair.</p>
      </div>
      <app-month-picker [month]="month()" (monthChange)="changeMonth($event)" />
    </header>

    <div class="segmented tabs mt-3" role="tablist">
      <button type="button" role="tab" [class.active]="tab() === 'all'"
              [attr.aria-selected]="tab() === 'all'" (click)="tab.set('all')">Lançamentos</button>
      <button type="button" role="tab" [class.active]="tab() === 'fixed'"
              [attr.aria-selected]="tab() === 'fixed'" (click)="tab.set('fixed')">Fixas</button>
    </div>

    @if (failed()) {
      <div class="notice notice-critical mt-3" role="alert">
        <i class="bi bi-exclamation-circle" aria-hidden="true"></i>
        <span>Não foi possível carregar as despesas.</span>
      </div>
    }

    @if (tab() === 'fixed') {
      <section class="stat-grid" aria-label="Comprometimento com despesas fixas">
        <article class="card-m stat">
          <h2>Fixas neste mês</h2>
          <p class="money">{{ money(summary()?.expenses_fixed) }}</p>
        </article>
        <article class="card-m stat">
          <h2>Parte da renda já comprometida</h2>
          <p class="money">{{ fixedShare() }}</p>
          <small>Sobre a renda prevista de {{ money(summary()?.income_expected) }}</small>
        </article>
      </section>
      <section class="card-m mt-3"><app-recurrence-list kind="expense" /></section>
    } @else {
      <form class="filters card-m" [formGroup]="filters" (submit)="$event.preventDefault()">
        <input class="form-control search" formControlName="q" type="search"
               placeholder="Buscar descrição" aria-label="Buscar descrição" />
        <select class="form-select" formControlName="category_id" aria-label="Categoria">
          <option value="">Todas as categorias</option>
          @for (c of categories(); track c.id) { <option [value]="c.id">{{ c.name }}</option> }
        </select>
        <select class="form-select" formControlName="account_id" aria-label="Conta">
          <option value="">Todas as contas</option>
          @for (a of accounts(); track a.id) { <option [value]="a.id">{{ a.name }}</option> }
        </select>
        <select class="form-select" formControlName="status" aria-label="Situação">
          <option value="">Pagas e pendentes</option>
          <option value="confirmed">Pagas</option>
          <option value="pending">Pendentes</option>
        </select>
        <input class="form-control" formControlName="min_amount" inputmode="decimal"
               placeholder="Valor mínimo" aria-label="Valor mínimo" />
        <input class="form-control" formControlName="max_amount" inputmode="decimal"
               placeholder="Valor máximo" aria-label="Valor máximo" />
      </form>

      <section class="card-m mt-3">
        <div class="section-head">
          <h2 class="card-title-m">
            {{ data()?.count ?? 0 }} {{ data()?.count === 1 ? 'lançamento' : 'lançamentos' }}
            · <span class="money">{{ money(data()?.total) }}</span>
          </h2>
          <button type="button" class="btn btn-quiet btn-sm" (click)="creating.set(true)">
            <i class="bi bi-plus-lg me-1" aria-hidden="true"></i>Nova despesa
          </button>
        </div>
        @if (data()?.items?.length) {
          <app-transaction-rows [items]="data()!.items" />
        } @else if (data()) {
          <p class="subtle mb-0">Nenhuma despesa encontrada.</p>
        }
        @if (pages() > 1) {
          <nav class="pager" aria-label="Páginas">
            <button type="button" class="btn btn-quiet btn-sm" [disabled]="page() <= 1" (click)="page.set(page() - 1)">Anterior</button>
            <span class="subtle">Página {{ page() }} de {{ pages() }}</span>
            <button type="button" class="btn btn-quiet btn-sm" [disabled]="page() >= pages()" (click)="page.set(page() + 1)">Próxima</button>
          </nav>
        }
      </section>
    }

    @if (creating()) {
      <app-transaction-form kind="expense" (closed)="creating.set(false)" />
    }
  `,
})
export class ExpensesPage {
  private readonly finance = inject(FinanceService);
  private request?: Subscription;

  protected readonly month = signal(todayIso().slice(0, 7));
  protected readonly tab = signal<'all' | 'fixed'>('all');
  protected readonly page = signal(1);
  protected readonly creating = signal(false);
  protected readonly failed = signal(false);
  protected readonly data = signal<TransactionPage | null>(null);
  protected readonly summary = signal<DashboardSummary | null>(null);
  protected readonly categories = signal<Category[]>([]);
  protected readonly accounts = signal<Account[]>([]);
  protected readonly money = formatMoney;

  protected readonly filters = new FormGroup({
    q: new FormControl('', { nonNullable: true }),
    category_id: new FormControl('', { nonNullable: true }),
    account_id: new FormControl('', { nonNullable: true }),
    status: new FormControl('', { nonNullable: true }),
    min_amount: new FormControl('', { nonNullable: true }),
    max_amount: new FormControl('', { nonNullable: true }),
  });
  private readonly filterValues = toSignal(
    this.filters.valueChanges.pipe(debounceTime(250)),
    { initialValue: this.filters.getRawValue() },
  );

  protected readonly pages = computed(() => {
    const d = this.data();
    return d ? Math.ceil(d.count / d.per_page) : 1;
  });
  protected readonly fixedShare = computed(() => {
    const s = this.summary();
    if (!s || Number(s.income_expected) <= 0) return '—';
    return `${Math.round((Number(s.expenses_fixed) / Number(s.income_expected)) * 100)}%`;
  });

  constructor() {
    this.finance.categories().subscribe((all) =>
      this.categories.set(all.filter((c) => c.kind === 'expense')),
    );
    effect(() => {
      this.finance.revision();
      const month = this.month();
      const page = this.page();
      const values = this.filterValues();
      untracked(() => this.load(month, page, values));
    });
  }

  protected changeMonth(month: string): void {
    this.page.set(1);
    this.month.set(month);
  }

  private load(month: string, page: number, values: Partial<typeof this.filters.value>): void {
    this.failed.set(false);
    const fail = () => this.failed.set(true);
    this.request?.unsubscribe();
    this.request = this.finance.transactions({
      ...values,
      min_amount: parseMoney(values.min_amount) ?? undefined,
      max_amount: parseMoney(values.max_amount) ?? undefined,
      month, kind: 'expense', page,
    }).subscribe({ next: (d) => this.data.set(d), error: fail });
    this.finance.dashboard(month).subscribe({ next: (d) => this.summary.set(d.summary), error: fail });
    this.finance.accounts().subscribe({ next: (a) => this.accounts.set(a), error: fail });
  }
}
