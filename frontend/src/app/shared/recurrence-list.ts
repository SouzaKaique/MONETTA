import { Component, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { FinanceService } from '../core/finance.service';
import { formatDate, formatMoney, frequencyLabel } from '../core/format';
import { apiMessage } from '../core/http';
import { Kind, Recurrence } from '../core/models';
import { RecurrenceForm } from './recurrence-form';

@Component({
  selector: 'app-recurrence-list',
  imports: [RecurrenceForm],
  template: `
    <div class="section-head">
      <h2 class="card-title-m">{{ title() }}</h2>
      <button type="button" class="btn btn-quiet btn-sm" (click)="creating.set(true)">
        <i class="bi bi-plus-lg me-1" aria-hidden="true"></i>Adicionar
      </button>
    </div>

    @if (error()) { <p class="field-error" role="alert">{{ error() }}</p> }

    @if (!rules().length && loaded()) {
      <p class="subtle mb-0">{{ empty() }}</p>
    }
    <ul class="rows">
      @for (rec of rules(); track rec.id) {
        <li class="row-item" [class.paused]="!rec.active">
          <div class="row-main">
            <strong>{{ rec.name }}</strong>
            <span class="row-meta">{{ schedule(rec) }}</span>
            <span class="tags">
              @if (rec.is_salary) { <span class="tag">Salário</span> }
              @if (!rec.active) { <span class="tag tag-pending">Pausada</span> }
              @if (rec.amount_history.length > 1) {
                <span class="tag">{{ rec.amount_history.length === 2 ? '1 reajuste' : rec.amount_history.length - 1 + ' reajustes' }}</span>
              }
            </span>
          </div>
          <span class="row-amount money">{{ money(rec.amount) }}</span>
          <div class="row-actions">
            <button type="button" class="icon-btn" [title]="rec.active ? 'Pausar' : 'Reativar'"
                    [attr.aria-label]="rec.active ? 'Pausar' : 'Reativar'" (click)="toggle(rec)">
              <i class="bi" [class.bi-pause]="rec.active" [class.bi-play]="!rec.active" aria-hidden="true"></i>
            </button>
            <button type="button" class="icon-btn" title="Editar" aria-label="Editar" (click)="editing.set(rec)">
              <i class="bi bi-pencil" aria-hidden="true"></i>
            </button>
            @if (deleting() === rec.id) {
              <button type="button" class="btn btn-sm btn-danger-quiet" (click)="remove(rec)">Excluir?</button>
            } @else {
              <button type="button" class="icon-btn" title="Excluir" aria-label="Excluir" (click)="deleting.set(rec.id)">
                <i class="bi bi-trash3" aria-hidden="true"></i>
              </button>
            }
          </div>
        </li>
      }
    </ul>

    @if (creating()) {
      <app-recurrence-form [kind]="kind()" (closed)="creating.set(false)" />
    }
    @if (editing(); as rec) {
      <app-recurrence-form [kind]="kind()" [recurrence]="rec" (closed)="editing.set(null)" />
    }
  `,
})
export class RecurrenceList {
  private readonly finance = inject(FinanceService);

  readonly kind = input.required<Kind>();
  protected readonly rules = signal<Recurrence[]>([]);
  protected readonly loaded = signal(false);
  protected readonly creating = signal(false);
  protected readonly editing = signal<Recurrence | null>(null);
  protected readonly deleting = signal<string | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly money = formatMoney;
  protected readonly title = computed(() =>
    this.kind() === 'income' ? 'Receitas recorrentes' : 'Despesas fixas',
  );
  protected readonly empty = computed(() =>
    this.kind() === 'income'
      ? 'Cadastre seu salário para o sistema prever a renda de cada mês.'
      : 'Cadastre aluguel, assinaturas e outras contas que se repetem.',
  );

  constructor() {
    effect(() => {
      this.finance.revision();
      const kind = this.kind();
      untracked(() => this.finance.recurrences(kind).subscribe((r) => {
        this.rules.set(r);
        this.loaded.set(true);
      }));
    });
  }

  protected schedule(rec: Recurrence): string {
    const when = rec.frequency === 'monthly' ? `todo dia ${rec.day_of_month}` : frequencyLabel(rec.frequency).toLowerCase();
    return rec.next_date ? `${when} · próxima em ${formatDate(rec.next_date)}` : when;
  }

  protected toggle(rec: Recurrence): void {
    this.error.set(null);
    this.finance.saveRecurrence({ active: !rec.active }, rec.id).subscribe({
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível alterar.')),
    });
  }

  protected remove(rec: Recurrence): void {
    this.error.set(null);
    this.finance.deleteRecurrence(rec.id).subscribe({
      next: () => this.deleting.set(null),
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível excluir.')),
    });
  }
}
