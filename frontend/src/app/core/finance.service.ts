import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import {
  Account, ApiTokenInfo, AppNotification, CalendarEvent, CardDetail, Category, CreditCard, Dashboard, Debt, DebtList,
  DebtSimulation, DebtStrategy, Installment, Invoice, InvoiceDetail, Kind, Planning, Purchase,
  PurchaseAdvice, Recovery, RecoveryImpact, Report, ReportPeriod, UntilSalary, WishlistData, WishlistItem, Recurrence, Transaction, TransactionPage, Transfer,
} from './models';

export interface TransactionFilters {
  month?: string;
  kind?: Kind;
  status?: string;
  category_id?: string;
  account_id?: string;
  min_amount?: string;
  max_amount?: string;
  q?: string;
  fixed?: 'true' | 'false';
  page?: number;
}

@Injectable({ providedIn: 'root' })
export class FinanceService {
  private readonly http = inject(HttpClient);

  /** Aumenta a cada escrita; as páginas observam este sinal para recarregar. */
  readonly revision = signal(0);

  private changed<T>(request: Observable<T>): Observable<T> {
    return request.pipe(tap(() => this.revision.update((v) => v + 1)));
  }

  dashboard(month?: string): Observable<Dashboard> {
    return this.http.get<Dashboard>('/api/dashboard', { params: month ? { month } : {} });
  }

  accounts(): Observable<Account[]> {
    return this.http.get<Account[]>('/api/accounts');
  }

  saveAccount(body: Partial<Account>, id?: string): Observable<Account> {
    return this.changed(
      id ? this.http.patch<Account>(`/api/accounts/${id}`, body)
         : this.http.post<Account>('/api/accounts', body),
    );
  }

  deleteAccount(id: string): Observable<unknown> {
    return this.changed(this.http.delete(`/api/accounts/${id}`));
  }

  transfers(): Observable<Transfer[]> {
    return this.http.get<Transfer[]>('/api/transfers');
  }

  createTransfer(body: object): Observable<Transfer> {
    return this.changed(this.http.post<Transfer>('/api/transfers', body));
  }

  deleteTransfer(id: string): Observable<unknown> {
    return this.changed(this.http.delete(`/api/transfers/${id}`));
  }

  categories(): Observable<Category[]> {
    return this.http.get<Category[]>('/api/categories');
  }

  saveCategory(body: Partial<Category>, id?: string): Observable<Category> {
    return this.changed(
      id ? this.http.patch<Category>(`/api/categories/${id}`, body)
         : this.http.post<Category>('/api/categories', body),
    );
  }

  deleteCategory(id: string): Observable<unknown> {
    return this.changed(this.http.delete(`/api/categories/${id}`));
  }

  transactions(filters: TransactionFilters): Observable<TransactionPage> {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== '') params = params.set(key, String(value));
    }
    return this.http.get<TransactionPage>('/api/transactions', { params });
  }

  /** A chave garante que um clique duplo ou uma nova tentativa não duplique o lançamento. */
  createTransaction(body: object, idempotencyKey: string): Observable<Transaction> {
    return this.changed(this.http.post<Transaction>('/api/transactions', body, {
      headers: { 'Idempotency-Key': idempotencyKey },
    }));
  }

  updateTransaction(id: string, body: object): Observable<Transaction> {
    return this.changed(this.http.patch<Transaction>(`/api/transactions/${id}`, body));
  }

  confirmTransaction(id: string, body: object): Observable<Transaction> {
    return this.changed(this.http.post<Transaction>(`/api/transactions/${id}/confirm`, body));
  }

  unconfirmTransaction(id: string): Observable<Transaction> {
    return this.changed(this.http.post<Transaction>(`/api/transactions/${id}/unconfirm`, {}));
  }

  deleteTransaction(id: string): Observable<unknown> {
    return this.changed(this.http.delete(`/api/transactions/${id}`));
  }

  recurrences(kind: Kind): Observable<Recurrence[]> {
    return this.http.get<Recurrence[]>('/api/recurrences', { params: { kind } });
  }

  saveRecurrence(body: object, id?: string): Observable<Recurrence> {
    return this.changed(
      id ? this.http.patch<Recurrence>(`/api/recurrences/${id}`, body)
         : this.http.post<Recurrence>('/api/recurrences', body),
    );
  }

  deleteRecurrence(id: string): Observable<unknown> {
    return this.changed(this.http.delete(`/api/recurrences/${id}`));
  }

  cards(): Observable<CreditCard[]> {
    return this.http.get<CreditCard[]>('/api/cards');
  }

  card(id: string): Observable<CardDetail> {
    return this.http.get<CardDetail>(`/api/cards/${id}`);
  }

  saveCard(body: object, id?: string): Observable<CreditCard> {
    return this.changed(
      id ? this.http.patch<CreditCard>(`/api/cards/${id}`, body)
         : this.http.post<CreditCard>('/api/cards', body),
    );
  }

  deleteCard(id: string): Observable<unknown> {
    return this.changed(this.http.delete(`/api/cards/${id}`));
  }

  invoice(id: string): Observable<InvoiceDetail> {
    return this.http.get<InvoiceDetail>(`/api/invoices/${id}`);
  }

  payInvoice(id: string, body: object, idempotencyKey: string): Observable<Invoice> {
    return this.changed(this.http.post<Invoice>(`/api/invoices/${id}/payments`, body, {
      headers: { 'Idempotency-Key': idempotencyKey },
    }));
  }

  deleteInvoicePayment(id: string): Observable<unknown> {
    return this.changed(this.http.delete(`/api/invoice-payments/${id}`));
  }

  purchases(cardId: string): Observable<Purchase[]> {
    return this.http.get<Purchase[]>(`/api/cards/${cardId}/purchases`);
  }

  createPurchase(cardId: string, body: object, idempotencyKey: string): Observable<Purchase> {
    return this.changed(this.http.post<Purchase>(`/api/cards/${cardId}/purchases`, body, {
      headers: { 'Idempotency-Key': idempotencyKey },
    }));
  }

  deletePurchase(id: string): Observable<unknown> {
    return this.changed(this.http.delete(`/api/purchases/${id}`));
  }

  debts(strategy?: DebtStrategy): Observable<DebtList> {
    return this.http.get<DebtList>('/api/debts', { params: strategy ? { strategy } : {} });
  }

  saveDebt(body: object, id?: string): Observable<Debt> {
    return this.changed(
      id ? this.http.patch<Debt>(`/api/debts/${id}`, body)
         : this.http.post<Debt>('/api/debts', body),
    );
  }

  deleteDebt(id: string): Observable<unknown> {
    return this.changed(this.http.delete(`/api/debts/${id}`));
  }

  reorderDebts(ids: string[]): Observable<unknown> {
    return this.changed(this.http.post('/api/debts/order', { ids }));
  }

  payDebt(id: string, body: object, idempotencyKey: string): Observable<Debt> {
    return this.changed(this.http.post<Debt>(`/api/debts/${id}/payments`, body, {
      headers: { 'Idempotency-Key': idempotencyKey },
    }));
  }

  deleteDebtPayment(id: string): Observable<unknown> {
    return this.changed(this.http.delete(`/api/debt-payments/${id}`));
  }

  simulateDebts(body: object): Observable<DebtSimulation> {
    return this.http.post<DebtSimulation>('/api/debts/simulate', body);
  }

  untilSalary(spend?: string): Observable<UntilSalary> {
    return this.http.get<UntilSalary>('/api/planning/until-salary', {
      params: spend ? { spend } : {},
    });
  }

  planning(month: string): Observable<Planning> {
    return this.http.get<Planning>('/api/planning', { params: { month } });
  }

  saveBudget(category_id: string, amount: string, month: string): Observable<unknown> {
    return this.changed(this.http.put('/api/budgets', { category_id, amount, month }));
  }

  calendar(month: string): Observable<{ month: string; events: CalendarEvent[] }> {
    return this.http.get<{ month: string; events: CalendarEvent[] }>('/api/calendar', {
      params: { month },
    });
  }

  transaction(id: string): Observable<Transaction> {
    return this.http.get<Transaction>(`/api/transactions/${id}`);
  }

  recovery(): Observable<Recovery> {
    return this.http.get<Recovery>('/api/recovery');
  }

  saveRecovery(body: object): Observable<Recovery> {
    return this.changed(this.http.put<Recovery>('/api/recovery', body));
  }

  deactivateRecovery(): Observable<Recovery> {
    return this.changed(this.http.post<Recovery>('/api/recovery/deactivate', {}));
  }

  recoveryImpact(amount: string): Observable<RecoveryImpact> {
    return this.http.post<RecoveryImpact>('/api/recovery/impact', { amount });
  }

  notifications(): Observable<{ unread: number; items: AppNotification[] }> {
    return this.http.get<{ unread: number; items: AppNotification[] }>('/api/notifications');
  }

  readNotification(id: string): Observable<unknown> {
    return this.changed(this.http.post(`/api/notifications/${id}/read`, {}));
  }

  readAllNotifications(): Observable<unknown> {
    return this.changed(this.http.post('/api/notifications/read-all', {}));
  }

  wishlist(): Observable<WishlistData> {
    return this.http.get<WishlistData>('/api/wishlist');
  }

  saveWishlistItem(body: object, id?: string): Observable<WishlistItem> {
    return this.changed(
      id ? this.http.patch<WishlistItem>(`/api/wishlist/${id}`, body)
         : this.http.post<WishlistItem>('/api/wishlist', body),
    );
  }

  deleteWishlistItem(id: string): Observable<unknown> {
    return this.changed(this.http.delete(`/api/wishlist/${id}`));
  }

  uploadWishlistImage(id: string, file: File): Observable<WishlistItem> {
    const data = new FormData();
    data.append('image', file);
    return this.changed(this.http.post<WishlistItem>(`/api/wishlist/${id}/image`, data));
  }

  contribute(id: string, body: object, idempotencyKey: string): Observable<WishlistItem> {
    return this.changed(this.http.post<WishlistItem>(`/api/wishlist/${id}/contributions`, body, {
      headers: { 'Idempotency-Key': idempotencyKey },
    }));
  }

  deleteContribution(id: string): Observable<unknown> {
    return this.changed(this.http.delete(`/api/goal-contributions/${id}`));
  }

  buyWishlistItem(id: string, body: object): Observable<WishlistItem> {
    return this.changed(this.http.post<WishlistItem>(`/api/wishlist/${id}/buy`, body));
  }

  giveUpWishlistItem(id: string): Observable<WishlistItem> {
    return this.changed(this.http.post<WishlistItem>(`/api/wishlist/${id}/give-up`, {}));
  }

  reopenWishlistItem(id: string): Observable<WishlistItem> {
    return this.changed(this.http.post<WishlistItem>(`/api/wishlist/${id}/reopen`, {}));
  }

  canBuy(body: object): Observable<PurchaseAdvice> {
    return this.http.post<PurchaseAdvice>('/api/wishlist/can-buy', body);
  }

  report(period: ReportPeriod, month: string): Observable<Report> {
    return this.http.get<Report>('/api/reports', { params: { period, month } });
  }

  restoreBackup(payload: unknown): Observable<unknown> {
    return this.changed(this.http.post('/api/backup/restore', payload));
  }

  tokens(): Observable<ApiTokenInfo[]> {
    return this.http.get<ApiTokenInfo[]>('/api/tokens');
  }

  createToken(name: string): Observable<{ id: string; name: string; token: string }> {
    return this.changed(this.http.post<{ id: string; name: string; token: string }>('/api/tokens', { name }));
  }

  revokeToken(id: string): Observable<unknown> {
    return this.changed(this.http.delete(`/api/tokens/${id}`));
  }

  installments(month: string): Observable<{ items: Installment[]; total: string }> {
    return this.http.get<{ items: Installment[]; total: string }>('/api/installments', {
      params: { month },
    });
  }
}
