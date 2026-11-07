import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FinanceService } from '../../core/finance.service';
import { formatDate, formatMoney, formatMonth, moneyToInput, parseMoney, todayIso } from '../../core/format';
import { apiMessage } from '../../core/http';
import { Account, CreditCard, WishlistData, WishlistItem, WishlistStatus } from '../../core/models';
import { Dialog } from '../../shared/dialog';
import { CanBuy } from './can-buy';
import { WishlistItemForm } from './item-form';

const STATUS: Record<WishlistStatus, string> = {
  desired: 'Desejado', planning: 'Planejando', saving: 'Economizando',
  bought: 'Comprado', given_up: 'Desistido',
};
const PRIORITY: Record<number, string> = { 1: 'Alta', 2: 'Média', 3: 'Baixa' };
const BROKEN = new Set<string>();

@Component({
  selector: 'app-wishlist',
  imports: [ReactiveFormsModule, CanBuy, Dialog, WishlistItemForm],
  templateUrl: './wishlist.html',
  styleUrl: './wishlist.css',
})
export class WishlistPage {
  private readonly finance = inject(FinanceService);

  protected readonly statusLabel = STATUS;
  protected readonly priorityLabel = PRIORITY;
  protected readonly filters: { value: string; label: string }[] = [
    { value: 'open', label: 'Em aberto' },
    { value: 'bought', label: 'Comprados' },
    { value: 'given_up', label: 'Desistidos' },
  ];
  protected readonly today = todayIso();
  protected readonly money = formatMoney;
  protected readonly date = formatDate;
  protected readonly monthLabel = formatMonth;

  protected readonly data = signal<WishlistData | null>(null);
  protected readonly accounts = signal<Account[]>([]);
  protected readonly cards = signal<CreditCard[]>([]);
  protected readonly filter = signal('open');
  protected readonly error = signal<string | null>(null);
  protected readonly formError = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly deleting = signal<string | null>(null);
  protected readonly creating = signal(false);
  protected readonly editing = signal<WishlistItem | null>(null);
  protected readonly saving = signal<WishlistItem | null>(null);
  protected readonly buying = signal<WishlistItem | null>(null);
  protected readonly checkingOpen = signal(false);
  protected readonly checking = signal<WishlistItem | null>(null);
  protected readonly history = signal<string | null>(null);
  protected readonly imageRevision = signal(0);
  private contributionKey = crypto.randomUUID();

  protected readonly shown = computed(() => {
    const items = this.data()?.items ?? [];
    const filter = this.filter();
    return items.filter((i) =>
      filter === 'open' ? !['bought', 'given_up'].includes(i.status) : i.status === filter,
    );
  });

  protected readonly saveForm = new FormGroup({
    amount: new FormControl('', { nonNullable: true }),
    kind: new FormControl('deposit', { nonNullable: true }),
    contributed_on: new FormControl(this.today, { nonNullable: true }),
  });
  protected readonly buyForm = new FormGroup({
    amount: new FormControl('', { nonNullable: true }),
    bought_on: new FormControl(this.today, { nonNullable: true }),
    source: new FormControl('', { nonNullable: true }),
    installments: new FormControl(1, { nonNullable: true }),
  });

  constructor() {
    effect(() => {
      this.finance.revision();
      untracked(() => {
        const fail = (e: unknown) => this.error.set(apiMessage(e, 'Não foi possível carregar a wishlist.'));
        this.finance.wishlist().subscribe({ next: (d) => this.data.set(d), error: fail });
        this.finance.accounts().subscribe({ next: (a) => this.accounts.set(a.filter((x) => x.active)), error: fail });
        this.finance.cards().subscribe({ next: (c) => this.cards.set(c.filter((x) => x.active)), error: fail });
        this.imageRevision.update((v) => v + 1);
      });
    });
  }

  protected image(item: WishlistItem): string | null {
    const source = item.has_upload
      ? `/api/wishlist/${item.id}/image?v=${this.imageRevision()}`
      : item.image_url;
    return source && !BROKEN.has(source) ? source : null;
  }

  protected imageFailed(item: WishlistItem): void {
    const source = this.image(item);
    if (source) BROKEN.add(source);
    this.data.update((d) => (d ? { ...d } : d));
  }

  protected openSave(item: WishlistItem): void {
    this.formError.set(null);
    this.contributionKey = crypto.randomUUID();
    const suggestion = item.monthly_amount && Number(item.monthly_amount) < Number(item.remaining)
      ? item.monthly_amount : item.remaining;
    this.saveForm.reset({
      amount: Number(suggestion) > 0 ? moneyToInput(suggestion) : '',
      kind: 'deposit', contributed_on: this.today,
    });
    this.saving.set(item);
  }

  protected submitSave(dialog: Dialog): void {
    const item = this.saving();
    if (!item || this.busy()) return;
    this.formError.set(null);
    const value = this.saveForm.getRawValue();
    const amount = parseMoney(value.amount);
    if (!amount || Number(amount) <= 0) {
      this.formError.set('Informe um valor válido, como 100,00.');
      return;
    }
    this.busy.set(true);
    this.finance.contribute(item.id, { ...value, amount }, this.contributionKey).subscribe({
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

  protected openBuy(item: WishlistItem): void {
    this.formError.set(null);
    const only = this.accounts().length === 1 ? `account:${this.accounts()[0].id}` : '';
    this.buyForm.reset({
      amount: moneyToInput(item.price), bought_on: this.today, source: only, installments: 1,
    });
    this.buying.set(item);
  }

  protected submitBuy(dialog: Dialog): void {
    const item = this.buying();
    if (!item || this.busy()) return;
    this.formError.set(null);
    const value = this.buyForm.getRawValue();
    const amount = parseMoney(value.amount);
    const [kind, id] = value.source.split(':');
    if (!amount || Number(amount) <= 0) {
      this.formError.set('Informe um valor válido, como 100,00.');
      return;
    }
    if (!id) {
      this.formError.set('Escolha como pagou.');
      return;
    }
    this.busy.set(true);
    this.finance.buyWishlistItem(item.id, {
      amount,
      bought_on: value.bought_on,
      account_id: kind === 'account' ? id : null,
      card_id: kind === 'card' ? id : null,
      installments: kind === 'card' ? value.installments || 1 : 1,
    }).subscribe({
      next: () => {
        this.busy.set(false);
        dialog.close();
      },
      error: (e) => {
        this.busy.set(false);
        this.formError.set(apiMessage(e, 'Não foi possível registrar a compra.'));
      },
    });
  }

  private run(action: { subscribe: (o: object) => unknown }): void {
    this.error.set(null);
    action.subscribe({
      next: () => this.deleting.set(null),
      error: (e: unknown) => {
        this.deleting.set(null);
        this.error.set(apiMessage(e, 'Não foi possível concluir.'));
      },
    });
  }

  protected giveUp(item: WishlistItem): void {
    this.run(this.finance.giveUpWishlistItem(item.id));
  }

  protected reopen(item: WishlistItem): void {
    this.run(this.finance.reopenWishlistItem(item.id));
  }

  protected remove(item: WishlistItem): void {
    this.run(this.finance.deleteWishlistItem(item.id));
  }

  protected removeContribution(id: string): void {
    this.run(this.finance.deleteContribution(id));
  }

  protected abs(value: string): string {
    return value.replace('-', '');
  }
}
