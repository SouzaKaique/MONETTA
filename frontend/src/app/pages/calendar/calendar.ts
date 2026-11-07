import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { FinanceService } from '../../core/finance.service';
import { formatDate, formatMoney, todayIso } from '../../core/format';
import { apiMessage } from '../../core/http';
import { CalendarEvent, Transaction } from '../../core/models';
import { ConfirmForm } from '../../shared/confirm-form';
import { Dialog } from '../../shared/dialog';
import { MonthPicker } from '../../shared/month-picker';
import { TransactionForm } from '../../shared/transaction-form';

const TYPES = [
  { key: 'salary', label: 'Salário', icon: 'bi-wallet2' },
  { key: 'income', label: 'Receitas', icon: 'bi-arrow-down-left-circle' },
  { key: 'bill', label: 'Contas', icon: 'bi-receipt' },
  { key: 'recurring', label: 'Recorrentes', icon: 'bi-arrow-repeat' },
  { key: 'invoice_closing', label: 'Fechamento', icon: 'bi-lock' },
  { key: 'invoice_due', label: 'Fatura', icon: 'bi-credit-card' },
  { key: 'debt', label: 'Dívidas', icon: 'bi-journal-check' },
  { key: 'goal', label: 'Metas', icon: 'bi-flag' },
];
const WEEKDAYS = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
const STORAGE_KEY = 'monetta-calendar-hidden';

interface Day {
  iso: string;
  day: number;
  events: CalendarEvent[];
}

@Component({
  selector: 'app-calendar',
  imports: [RouterLink, ConfirmForm, Dialog, MonthPicker, TransactionForm],
  templateUrl: './calendar.html',
  styleUrl: './calendar.css',
})
export class CalendarPage {
  private readonly finance = inject(FinanceService);

  protected readonly types = TYPES;
  protected readonly weekdays = WEEKDAYS;
  protected readonly today = todayIso();
  protected readonly money = formatMoney;
  protected readonly date = formatDate;

  protected readonly month = signal(this.today.slice(0, 7));
  protected readonly events = signal<CalendarEvent[]>([]);
  protected readonly hidden = signal<string[]>(this.storedFilters());
  protected readonly error = signal<string | null>(null);
  protected readonly selected = signal<CalendarEvent | null>(null);
  protected readonly confirming = signal<Transaction | null>(null);
  protected readonly editing = signal<Transaction | null>(null);

  protected readonly visible = computed(() =>
    this.events().filter((e) => !this.hidden().includes(e.type)),
  );

  /** Dias vazios no início alinham o dia 1 ao dia da semana certo. */
  protected readonly leading = computed(() => {
    const [year, month] = this.month().split('-').map(Number);
    return Array.from({ length: new Date(Date.UTC(year, month - 1, 1)).getUTCDay() });
  });

  protected readonly days = computed<Day[]>(() => {
    const [year, month] = this.month().split('-').map(Number);
    const count = new Date(Date.UTC(year, month, 0)).getUTCDate();
    const prefix = this.month();
    return Array.from({ length: count }, (_, index) => {
      const iso = `${prefix}-${String(index + 1).padStart(2, '0')}`;
      return { iso, day: index + 1, events: this.visible().filter((e) => e.date === iso) };
    });
  });

  protected readonly listDays = computed(() => this.days().filter((d) => d.events.length));

  constructor() {
    effect(() => {
      this.finance.revision();
      const month = this.month();
      untracked(() => this.finance.calendar(month).subscribe({
        next: (r) => this.events.set(r.events),
        error: (e) => this.error.set(apiMessage(e, 'Não foi possível carregar o calendário.')),
      }));
    });
  }

  private storedFilters(): string[] {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]');
    } catch {
      return [];
    }
  }

  protected toggleType(key: string): void {
    this.hidden.update((all) => (all.includes(key) ? all.filter((k) => k !== key) : [...all, key]));
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.hidden()));
    } catch {
      // Sem armazenamento local, o filtro vale só para esta visita.
    }
  }

  protected icon(type: string): string {
    return TYPES.find((t) => t.key === type)?.icon ?? 'bi-dot';
  }

  protected typeLabel(type: string): string {
    return TYPES.find((t) => t.key === type)?.label ?? type;
  }

  /** Abre o formulário certo depois de buscar o lançamento atualizado. */
  protected openTransaction(event: CalendarEvent, action: 'confirm' | 'edit'): void {
    if (!event.transaction_id) return;
    this.finance.transaction(event.transaction_id).subscribe({
      next: (tx) => {
        this.selected.set(null);
        (action === 'confirm' ? this.confirming : this.editing).set(tx);
      },
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível abrir o lançamento.')),
    });
  }
}
