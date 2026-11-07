import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { FinanceService } from '../../core/finance.service';
import { formatMoney, moneyToInput, parseMoney, todayIso } from '../../core/format';
import { apiMessage } from '../../core/http';
import { BudgetRow, Category, Planning } from '../../core/models';
import { Dialog } from '../../shared/dialog';
import { MonthPicker } from '../../shared/month-picker';

@Component({
  selector: 'app-planning',
  imports: [ReactiveFormsModule, RouterLink, Dialog, MonthPicker],
  templateUrl: './planning.html',
  styleUrl: './planning.css',
})
export class PlanningPage {
  private readonly finance = inject(FinanceService);
  private readonly auth = inject(AuthService);

  protected readonly currentMonth = todayIso().slice(0, 7);
  protected readonly month = signal(this.currentMonth);
  protected readonly data = signal<Planning | null>(null);
  protected readonly categories = signal<Category[]>([]);
  protected readonly recoveryActive = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly formError = signal<string | null>(null);
  protected readonly editing = signal(false);
  protected readonly busy = signal(false);
  protected readonly reserveSaved = signal(false);
  protected readonly money = formatMoney;

  protected readonly canEdit = computed(() => this.month() >= this.currentMonth);
  protected readonly commitmentWidth = computed(() => Math.min(this.data()?.commitment_pct ?? 0, 100));
  protected readonly commitmentLevel = computed(() => {
    const pct = this.data()?.commitment_pct ?? 0;
    return pct >= 100 ? 'over' : pct >= 80 ? 'high' : 'ok';
  });
  private readonly maxPart = computed(() =>
    Math.max(0, ...(this.data()?.distribution ?? []).map((d) => Number(d.amount ?? 0))),
  );

  protected readonly reserve = new FormControl(
    moneyToInput(this.auth.user()?.planned_reserve), { nonNullable: true },
  );
  protected readonly budgetForm = new FormGroup({
    category_id: new FormControl('', { nonNullable: true }),
    amount: new FormControl('', { nonNullable: true }),
  });

  constructor() {
    this.finance.categories().subscribe((all) =>
      this.categories.set(all.filter((c) => c.kind === 'expense')),
    );
    effect(() => {
      this.finance.revision();
      const month = this.month();
      untracked(() => {
        this.finance.planning(month).subscribe({
          next: (d) => this.data.set(d),
          error: (e) => this.error.set(apiMessage(e, 'Não foi possível carregar o planejamento.')),
        });
        this.finance.recovery().subscribe((r) => this.recoveryActive.set(r.active));
      });
    });
  }

  protected partWidth(amount: string | null): number {
    const max = this.maxPart();
    return max > 0 ? Math.max(0, (Number(amount ?? 0) / max) * 100) : 0;
  }

  protected budgetWidth(row: BudgetRow): number {
    return Math.min(row.pct ?? 0, 100);
  }

  protected openBudget(row: BudgetRow | null): void {
    this.formError.set(null);
    this.budgetForm.reset({
      category_id: row?.category_id ?? '',
      amount: moneyToInput(row?.limit),
    });
    this.editing.set(true);
  }

  protected saveBudget(dialog: Dialog): void {
    if (this.busy()) return;
    this.formError.set(null);
    const value = this.budgetForm.getRawValue();
    const amount = value.amount.trim() === '' ? '0' : parseMoney(value.amount);
    if (!value.category_id) {
      this.formError.set('Escolha a categoria.');
      return;
    }
    if (amount === null || Number(amount) < 0) {
      this.formError.set('Informe um valor válido, como 300,00.');
      return;
    }
    this.busy.set(true);
    this.finance.saveBudget(value.category_id, amount, this.month()).subscribe({
      next: () => {
        this.busy.set(false);
        dialog.close();
      },
      error: (e) => {
        this.busy.set(false);
        this.formError.set(apiMessage(e, 'Não foi possível salvar.'));
      },
    });
  }

  protected saveReserve(): void {
    this.reserveSaved.set(false);
    this.error.set(null);
    const value = this.reserve.value.trim() === '' ? '0' : parseMoney(this.reserve.value);
    if (value === null || Number(value) < 0) {
      this.error.set('Informe uma reserva válida, como 200,00.');
      return;
    }
    this.auth.updateProfile({ planned_reserve: value }).subscribe({
      next: () => {
        this.reserveSaved.set(true);
        this.finance.revision.update((v) => v + 1);
      },
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível salvar.')),
    });
  }
}
