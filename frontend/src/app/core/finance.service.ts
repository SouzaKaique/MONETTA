import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import {
  Account, CardDetail, Category, CreditCard, Dashboard, Installment, Invoice, InvoiceDetail, Kind,
  Purchase, Recurrence, Transaction, TransactionPage, Transfer,
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

  installments(month: string): Observable<{ items: Installment[]; total: string }> {
    return this.http.get<{ items: Installment[]; total: string }>('/api/installments', {
      params: { month },
    });
  }
}
