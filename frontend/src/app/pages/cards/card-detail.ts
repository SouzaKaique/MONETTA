import { Component, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { FinanceService } from '../../core/finance.service';
import { formatDate, formatMoney, formatMonth, formatMonthShort, moneyToInput, parseMoney, todayIso } from '../../core/format';
import { apiMessage } from '../../core/http';
import { Account, CardDetail, Invoice, InvoiceDetail, InvoiceStatus, Purchase } from '../../core/models';
import { Dialog } from '../../shared/dialog';
import { PurchaseForm } from '../../shared/purchase-form';
import { CardForm } from './card-form';

const STATUS: Record<InvoiceStatus, { label: string; tag: string }> = {
  future: { label: 'Futura', tag: '' },
  open: { label: 'Atual', tag: 'tag-pending' },
  closed: { label: 'Fechada', tag: 'tag-pending' },
  partial: { label: 'Parcial', tag: 'tag-pending' },
  paid: { label: 'Paga', tag: 'tag-ok' },
  overdue: { label: 'Atrasada', tag: 'tag-late' },
};

@Component({
  selector: 'app-card-detail',
  imports: [ReactiveFormsModule, RouterLink, Dialog, CardForm, PurchaseForm],
  templateUrl: './card-detail.html',
  styleUrl: './card-detail.css',
})
export class CardDetailPage {
  private readonly finance = inject(FinanceService);
  private readonly router = inject(Router);

  /** Vem da rota /cartoes/:id. */
  readonly id = input.required<string>();

  protected readonly status = STATUS;
  protected readonly today = todayIso();
  protected readonly money = formatMoney;
  protected readonly date = formatDate;
  protected readonly monthLabel = formatMonth;
  protected readonly monthShort = formatMonthShort;

  protected readonly card = signal<CardDetail | null>(null);
  protected readonly purchases = signal<Purchase[]>([]);
  protected readonly selectedId = signal<string | null>(null);
  protected readonly invoice = signal<InvoiceDetail | null>(null);
  protected readonly accounts = signal<Account[]>([]);
  protected readonly error = signal<string | null>(null);
  protected readonly editing = signal(false);
  protected readonly buying = signal(false);
  protected readonly paying = signal(false);
  protected readonly deleting = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly payError = signal<string | null>(null);
  private payKey = crypto.randomUUID();

  protected readonly payForm = new FormGroup({
    amount: new FormControl('', { nonNullable: true }),
    paid_on: new FormControl(this.today, { nonNullable: true }),
    account_id: new FormControl('', { nonNullable: true }),
  });

  protected readonly usageWidth = computed(() => Math.min(this.card()?.usage_pct ?? 0, 100));
  protected readonly maxSpending = computed(() =>
    Math.max(0, ...(this.card()?.spending ?? []).map((s) => Number(s.total))),
  );

  constructor() {
    effect(() => {
      this.finance.revision();
      const id = this.id();
      untracked(() => this.load(id));
    });
    effect(() => {
      const invoiceId = this.selectedId();
      this.finance.revision();
      untracked(() => {
        if (invoiceId) this.finance.invoice(invoiceId).subscribe((i) => this.invoice.set(i));
        else this.invoice.set(null);
      });
    });
  }

  private load(id: string): void {
    const fail = (e: unknown) => this.error.set(apiMessage(e, 'Não foi possível carregar o cartão.'));
    this.finance.card(id).subscribe({
      next: (card) => {
        this.card.set(card);
        const stillThere = card.invoices.some((i) => i.id === this.selectedId());
        if (!stillThere) this.selectedId.set(this.defaultInvoice(card.invoices)?.id ?? null);
      },
      error: fail,
    });
    this.finance.purchases(id).subscribe({ next: (p) => this.purchases.set(p), error: fail });
    this.finance.accounts().subscribe({
      next: (a) => this.accounts.set(a.filter((x) => x.active)),
      error: fail,
    });
  }

  /** Abre na fatura que pede atenção: a mais antiga ainda não paga. */
  private defaultInvoice(invoices: Invoice[]): Invoice | undefined {
    return invoices.find((i) => i.status !== 'paid') ?? invoices[invoices.length - 1];
  }

  protected barWidth(total: string): number {
    const max = this.maxSpending();
    return max > 0 ? (Number(total) / max) * 100 : 0;
  }

  protected openPay(): void {
    const invoice = this.invoice();
    if (!invoice) return;
    this.payError.set(null);
    this.payKey = crypto.randomUUID();
    const only = this.accounts().length === 1 ? this.accounts()[0].id : '';
    this.payForm.reset({ amount: moneyToInput(invoice.remaining), paid_on: this.today, account_id: only });
    this.paying.set(true);
  }

  protected pay(dialog: Dialog): void {
    const invoice = this.invoice();
    if (!invoice || this.busy()) return;
    this.payError.set(null);
    const value = this.payForm.getRawValue();
    const amount = parseMoney(value.amount);
    if (!amount || Number(amount) <= 0) {
      this.payError.set('Informe um valor válido, como 89,90.');
      return;
    }
    if (!value.account_id) {
      this.payError.set('Escolha a conta.');
      return;
    }
    this.busy.set(true);
    this.finance.payInvoice(invoice.id, { ...value, amount }, this.payKey).subscribe({
      next: () => {
        this.busy.set(false);
        dialog.close();
      },
      error: (e) => {
        this.busy.set(false);
        this.payError.set(apiMessage(e, 'Não foi possível registrar o pagamento.'));
      },
    });
  }

  protected removePayment(id: string): void {
    this.finance.deleteInvoicePayment(id).subscribe({
      next: () => this.deleting.set(null),
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível remover.')),
    });
  }

  protected removePurchase(purchase: Purchase): void {
    this.error.set(null);
    this.finance.deletePurchase(purchase.id).subscribe({
      next: () => this.deleting.set(null),
      error: (e) => {
        this.deleting.set(null);
        this.error.set(apiMessage(e, 'Não foi possível excluir.'));
      },
    });
  }

  protected toggleActive(card: CardDetail): void {
    this.finance.saveCard({ active: !card.active }, card.id).subscribe({
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível alterar.')),
    });
  }

  protected removeCard(card: CardDetail): void {
    this.error.set(null);
    this.finance.deleteCard(card.id).subscribe({
      next: () => void this.router.navigateByUrl('/cartoes'),
      error: (e) => {
        this.deleting.set(null);
        this.error.set(apiMessage(e, 'Não foi possível excluir.'));
      },
    });
  }
}
