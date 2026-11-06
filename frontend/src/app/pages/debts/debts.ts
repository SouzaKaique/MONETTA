import { NgTemplateOutlet } from '@angular/common';
import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { AuthService } from '../../core/auth.service';
import { FinanceService } from '../../core/finance.service';
import { formatDate, formatMoney } from '../../core/format';
import { apiMessage } from '../../core/http';
import { Debt, DebtList, DebtStrategy } from '../../core/models';
import { DebtForm } from './debt-form';
import { DebtPaymentForm } from './debt-payment-form';
import { DebtSimulator } from './debt-simulator';

const STATUS = { pending: 'Pendente', in_payment: 'Em pagamento', paid: 'Quitada' };
const PRIORITY: Record<number, string> = { 1: 'Alta', 2: 'Média', 3: 'Baixa' };
const FREQUENCY: Record<string, string> = {
  monthly: 'por mês', biweekly: 'por quinzena', weekly: 'por semana',
};

@Component({
  selector: 'app-debts',
  imports: [NgTemplateOutlet, DebtForm, DebtPaymentForm, DebtSimulator],
  templateUrl: './debts.html',
  styleUrl: './debts.css',
})
export class DebtsPage {
  private readonly finance = inject(FinanceService);
  private readonly auth = inject(AuthService);

  protected readonly strategies: { value: DebtStrategy; label: string; hint: string }[] = [
    { value: 'snowball', label: 'Bola de neve', hint: 'Começa pela menor dívida.' },
    { value: 'avalanche', label: 'Avalanche', hint: 'Começa pelos maiores juros. Dívidas sem juros ficam por último.' },
    { value: 'due_date', label: 'Vencimento', hint: 'Começa pelo vencimento mais próximo.' },
    { value: 'priority', label: 'Importância', hint: 'Segue a importância que você definiu.' },
    { value: 'custom', label: 'Minha ordem', hint: 'Use as setas para definir a ordem.' },
  ];
  protected readonly statusLabel = STATUS;
  protected readonly priorityLabel = PRIORITY;
  protected readonly frequencyLabel = FREQUENCY;
  protected readonly money = formatMoney;
  protected readonly date = formatDate;

  protected readonly strategy = signal<DebtStrategy>(this.auth.user()?.debt_strategy ?? 'snowball');
  protected readonly data = signal<DebtList | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly creating = signal(false);
  protected readonly editing = signal<Debt | null>(null);
  protected readonly paying = signal<Debt | null>(null);
  protected readonly open = signal<string | null>(null);
  protected readonly deleting = signal<string | null>(null);

  protected readonly active = computed(() =>
    (this.data()?.items ?? []).filter((d) => d.status !== 'paid'),
  );
  protected readonly finished = computed(() =>
    (this.data()?.items ?? []).filter((d) => d.status === 'paid'),
  );
  protected readonly hint = computed(
    () => this.strategies.find((s) => s.value === this.strategy())?.hint ?? '',
  );

  constructor() {
    effect(() => {
      this.finance.revision();
      const strategy = this.strategy();
      untracked(() => this.finance.debts(strategy).subscribe({
        next: (d) => this.data.set(d),
        error: (e) => this.error.set(apiMessage(e, 'Não foi possível carregar as dívidas.')),
      }));
    });
  }

  protected choose(strategy: DebtStrategy): void {
    this.strategy.set(strategy);
    this.auth.updateProfile({ debt_strategy: strategy }).subscribe({
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível salvar a estratégia.')),
    });
  }

  protected move(index: number, delta: number): void {
    const ids = this.active().map((d) => d.id);
    const target = index + delta;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    const all = [...ids, ...this.finished().map((d) => d.id)];
    this.finance.reorderDebts(all).subscribe({
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível mudar a ordem.')),
    });
  }

  protected toggle(debt: Debt): void {
    this.open.set(this.open() === debt.id ? null : debt.id);
  }

  protected remove(debt: Debt): void {
    this.error.set(null);
    this.finance.deleteDebt(debt.id).subscribe({
      next: () => this.deleting.set(null),
      error: (e) => {
        this.deleting.set(null);
        this.error.set(apiMessage(e, 'Não foi possível excluir.'));
      },
    });
  }

  protected removePayment(id: string): void {
    this.finance.deleteDebtPayment(id).subscribe({
      next: () => this.deleting.set(null),
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível remover.')),
    });
  }
}
