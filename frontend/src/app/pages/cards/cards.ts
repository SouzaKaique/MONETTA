import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { FinanceService } from '../../core/finance.service';
import { formatDate, formatMoney } from '../../core/format';
import { apiMessage } from '../../core/http';
import { CreditCard } from '../../core/models';
import { PurchaseForm } from '../../shared/purchase-form';
import { CardForm } from './card-form';

@Component({
  selector: 'app-cards',
  imports: [RouterLink, CardForm, PurchaseForm],
  template: `
    <header class="page-head">
      <div>
        <h1 class="page-title">Cartões</h1>
        <p class="muted mb-0">Limites, faturas e parcelas que ainda vão pesar.</p>
      </div>
      <div class="d-flex gap-2">
        @if (active().length) {
          <button type="button" class="btn btn-quiet" (click)="buying.set(true)">Nova compra</button>
        }
        <button type="button" class="btn btn-brand" (click)="creating.set(true)">
          <i class="bi bi-plus-lg me-1" aria-hidden="true"></i>Cartão
        </button>
      </div>
    </header>

    @if (error()) {
      <div class="notice notice-critical mt-3" role="alert">
        <i class="bi bi-exclamation-circle" aria-hidden="true"></i><span>{{ error() }}</span>
      </div>
    }

    @if (loaded() && !cards().length) {
      <div class="card-m mt-3">
        <p class="mb-0 muted">Cadastre seu primeiro cartão com o limite e os dias de fechamento e vencimento.</p>
      </div>
    }

    <section class="card-grid">
      @for (card of cards(); track card.id) {
        <a class="credit-card card-{{ card.color }}" [class.inactive]="!card.active" [routerLink]="['/cartoes', card.id]">
          <div class="top">
            <span class="name">{{ card.name }}</span>
            <span class="bank">{{ card.active ? card.institution : 'Inativo' }}</span>
          </div>
          <div>
            <small>Limite disponível</small>
            <p class="value money">{{ money(card.available) }}</p>
            <div class="usage" role="meter" aria-label="Limite utilizado"
                 [attr.aria-valuenow]="width(card)" aria-valuemin="0" aria-valuemax="100">
              <span [style.width.%]="width(card)"></span>
            </div>
            <small class="foot">
              <span>{{ card.usage_pct ?? 0 }}% de {{ money(card.credit_limit) }}</span>
              @if (card.next_due_date) {
                <span>{{ money(card.next_due_amount) }} em {{ date(card.next_due_date) }}</span>
              }
            </small>
          </div>
        </a>
      }
    </section>

    @if (creating()) { <app-card-form (closed)="creating.set(false)" /> }
    @if (buying()) { <app-purchase-form (closed)="buying.set(false)" /> }
  `,
  styles: `
    .card-grid {
      display: grid;
      gap: 0.75rem;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      margin-top: 1.25rem;
    }
    .credit-card {
      border-radius: var(--radius);
      color: #f6f5f0;
      display: flex;
      flex-direction: column;
      gap: 1.75rem;
      justify-content: space-between;
      min-height: 190px;
      padding: 1.25rem;
      text-decoration: none;
      transition: transform 120ms ease-out;
    }
    .credit-card:hover { transform: translateY(-2px); }
    .credit-card.inactive { opacity: 0.6; }
    .top { align-items: baseline; display: flex; justify-content: space-between; gap: 0.5rem; }
    .name { font-family: var(--font-display); font-size: 1.25rem; }
    .bank, small { color: rgb(246 245 240 / 78%); font-size: 0.75rem; }
    .value { font-size: 1.5rem; font-weight: 600; margin: 0 0 0.5rem; }
    .usage { background: rgb(246 245 240 / 20%); border-radius: 3px; height: 6px; overflow: hidden; }
    .usage span { background: #f6f5f0; display: block; height: 100%; }
    .foot { display: flex; flex-wrap: wrap; gap: 0.25rem 1rem; justify-content: space-between; margin-top: 0.4rem; }
  `,
})
export class CardsPage {
  private readonly finance = inject(FinanceService);

  protected readonly cards = signal<CreditCard[]>([]);
  protected readonly active = computed(() => this.cards().filter((c) => c.active));
  protected readonly loaded = signal(false);
  protected readonly creating = signal(false);
  protected readonly buying = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly money = formatMoney;
  protected readonly date = formatDate;

  constructor() {
    effect(() => {
      this.finance.revision();
      untracked(() => this.finance.cards().subscribe({
        next: (cards) => {
          this.cards.set(cards);
          this.loaded.set(true);
        },
        error: (e) => this.error.set(apiMessage(e, 'Não foi possível carregar os cartões.')),
      }));
    });
  }

  protected width(card: CreditCard): number {
    return Math.min(card.usage_pct ?? 0, 100);
  }
}
