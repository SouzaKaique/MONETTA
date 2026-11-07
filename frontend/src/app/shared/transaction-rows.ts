import { Component, inject, input, signal } from '@angular/core';
import { FinanceService } from '../core/finance.service';
import { formatDate, formatMoney, todayIso } from '../core/format';
import { Transaction } from '../core/models';
import { ConfirmForm } from './confirm-form';
import { TransactionForm } from './transaction-form';

@Component({
  selector: 'app-transaction-rows',
  imports: [ConfirmForm, TransactionForm],
  template: `
    <ul class="rows">
      @for (tx of items(); track tx.id) {
        <li class="row-item">
          <div class="row-main">
            <strong>{{ tx.description }}</strong>
            <span class="row-meta">
              {{ date(tx.competence_date) }}
              @if (tx.category_name) { · {{ tx.category_name }} }
              @if (tx.account_name) { · {{ tx.account_name }} }
            </span>
            <span class="tags">
              @if (tx.is_salary) { <span class="tag">Salário</span> }
              @if (tx.is_fixed && !tx.is_salary) { <span class="tag">Fixa</span> }
              @if (tx.status === 'pending') {
                @if (isLate(tx)) {
                  <span class="tag tag-late">Atrasada</span>
                } @else {
                  <span class="tag tag-pending">{{ tx.kind === 'income' ? 'Prevista' : 'Pendente' }}</span>
                }
              }
            </span>
          </div>
          <span class="row-amount money" [class.income]="tx.kind === 'income'">
            {{ tx.kind === 'income' ? '+' : '−' }} {{ money(tx.amount) }}
          </span>
          <div class="row-actions">
            @if (tx.status === 'pending') {
              <button type="button" class="btn btn-quiet btn-sm" (click)="confirming.set(tx)">
                {{ tx.kind === 'income' ? 'Recebi' : 'Paguei' }}
              </button>
            } @else {
              <button type="button" class="icon-btn" title="Desfazer confirmação"
                      aria-label="Desfazer confirmação" (click)="undo(tx)">
                <i class="bi bi-arrow-counterclockwise" aria-hidden="true"></i>
              </button>
            }
            <button type="button" class="icon-btn" title="Editar" aria-label="Editar" (click)="editing.set(tx)">
              <i class="bi bi-pencil" aria-hidden="true"></i>
            </button>
            @if (deleting() === tx.id) {
              <button type="button" class="btn btn-sm btn-danger-quiet" (click)="remove(tx)">Excluir?</button>
            } @else {
              <button type="button" class="icon-btn" title="Excluir" aria-label="Excluir" (click)="deleting.set(tx.id)">
                <i class="bi bi-trash3" aria-hidden="true"></i>
              </button>
            }
          </div>
        </li>
      }
    </ul>

    @if (confirming(); as tx) {
      <app-confirm-form [transaction]="tx" (closed)="confirming.set(null)" />
    }
    @if (editing(); as tx) {
      <app-transaction-form [kind]="tx.kind" [transaction]="tx" (closed)="editing.set(null)" />
    }
  `,
})
export class TransactionRows {
  private readonly finance = inject(FinanceService);

  readonly items = input.required<Transaction[]>();
  protected readonly confirming = signal<Transaction | null>(null);
  protected readonly editing = signal<Transaction | null>(null);
  protected readonly deleting = signal<string | null>(null);
  protected readonly money = formatMoney;
  protected readonly date = formatDate;
  private readonly today = todayIso();

  protected isLate(tx: Transaction): boolean {
    return tx.kind === 'expense' && tx.competence_date < this.today;
  }

  protected undo(tx: Transaction): void {
    this.finance.unconfirmTransaction(tx.id).subscribe();
  }

  protected remove(tx: Transaction): void {
    this.finance.deleteTransaction(tx.id).subscribe(() => this.deleting.set(null));
  }
}
