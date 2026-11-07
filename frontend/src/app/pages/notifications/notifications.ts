import { Component, effect, inject, signal, untracked } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { FinanceService } from '../../core/finance.service';
import { formatDate } from '../../core/format';
import { apiMessage } from '../../core/http';
import { AppNotification } from '../../core/models';

const ICONS = { info: 'bi-check-circle', warning: 'bi-exclamation-triangle', critical: 'bi-exclamation-octagon' };

@Component({
  selector: 'app-notifications',
  imports: [RouterLink],
  template: `
    <header class="page-head">
      <div>
        <h1 class="page-title">Notificações</h1>
        <p class="muted mb-0">
          {{ unread() ? unread() + (unread() === 1 ? ' não lida.' : ' não lidas.') : 'Tudo em dia.' }}
          <a routerLink="/configuracoes">Preferências</a>
        </p>
      </div>
      @if (unread()) {
        <button type="button" class="btn btn-quiet" (click)="readAll()">Marcar todas como lidas</button>
      }
    </header>

    @if (error()) {
      <div class="notice notice-critical mt-3" role="alert">
        <i class="bi bi-exclamation-circle" aria-hidden="true"></i><span>{{ error() }}</span>
      </div>
    }

    <section class="card-m mt-3 list">
      @if (loaded() && !items().length) {
        <p class="subtle mb-0">Nenhuma notificação por enquanto.</p>
      }
      @for (n of items(); track n.id) {
        <button type="button" class="item" [class.unread]="!n.read" (click)="open(n)">
          <i class="bi {{ icons[n.level] }} level-{{ n.level }}" aria-hidden="true"></i>
          <span class="body">
            <span>{{ n.message }}</span>
            <small>{{ date(n.created_at) }}</small>
          </span>
          @if (!n.read) { <span class="dot" aria-label="Não lida"></span> }
        </button>
      }
    </section>
  `,
  styles: `
    .list { padding: 0.25rem 1rem; }
    .list > .subtle { padding: 0.75rem 0; }
    .item {
      align-items: flex-start;
      background: none;
      border: 0;
      border-top: 1px solid var(--border);
      color: var(--ink-2);
      display: flex;
      gap: 0.65rem;
      padding: 0.7rem 0;
      text-align: left;
      width: 100%;
    }
    .item:first-of-type { border-top: 0; }
    .item.unread { color: var(--ink); font-weight: 500; }
    .body { display: flex; flex: 1; flex-direction: column; min-width: 0; }
    small { color: var(--ink-3); font-weight: 400; }
    .level-info { color: var(--accent); }
    .level-warning { color: var(--warning); }
    .level-critical { color: var(--negative); }
    .dot { background: var(--accent); border-radius: 50%; flex: none; height: 8px; margin-top: 0.4rem; width: 8px; }
  `,
})
export class NotificationsPage {
  private readonly finance = inject(FinanceService);
  private readonly router = inject(Router);

  protected readonly items = signal<AppNotification[]>([]);
  protected readonly unread = signal(0);
  protected readonly loaded = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly icons = ICONS;
  protected readonly date = formatDate;

  constructor() {
    effect(() => {
      this.finance.revision();
      untracked(() => this.finance.notifications().subscribe({
        next: (n) => {
          this.items.set(n.items);
          this.unread.set(n.unread);
          this.loaded.set(true);
        },
        error: (e) => this.error.set(apiMessage(e, 'Não foi possível carregar as notificações.')),
      }));
    });
  }

  protected open(item: AppNotification): void {
    const go = () => {
      if (item.link) void this.router.navigateByUrl(item.link);
    };
    if (item.read) {
      go();
      return;
    }
    this.finance.readNotification(item.id).subscribe({
      next: go,
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível marcar como lida.')),
    });
  }

  protected readAll(): void {
    this.finance.readAllNotifications().subscribe({
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível marcar como lidas.')),
    });
  }
}
