import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, catchError, firstValueFrom, map, of, tap } from 'rxjs';
import { DebtStrategy, Providers, ThemePreference, User } from './models';
import { ThemeService } from './theme.service';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly theme = inject(ThemeService);
  private loaded = false;

  readonly user = signal<User | null>(null);
  readonly isLoggedIn = computed(() => this.user() !== null);

  private accept(user: User): void {
    this.loaded = true;
    this.user.set(user);
    this.theme.set(user.theme);
  }

  /** Resolve a sessão atual uma vez; usado pelos guards. */
  async ensureLoaded(): Promise<User | null> {
    if (!this.loaded) {
      const user = await firstValueFrom(
        this.http.get<User>('/api/auth/me').pipe(catchError(() => of(null))),
      );
      this.loaded = true;
      if (user) this.accept(user);
    }
    return this.user();
  }

  providers(): Observable<Providers> {
    return this.http.get<Providers>('/api/auth/providers');
  }

  register(body: { account_name: string; email: string; password: string }): Observable<User> {
    return this.http.post<User>('/api/auth/register', body).pipe(tap((u) => this.accept(u)));
  }

  login(body: { email: string; password: string }): Observable<User> {
    return this.http.post<User>('/api/auth/login', body).pipe(tap((u) => this.accept(u)));
  }

  /** Navegação completa: o provedor precisa assumir a janela. */
  startSocial(provider: 'google' | 'apple'): void {
    location.assign(`/api/auth/${provider}/start`);
  }

  logout(everywhere = false): Observable<void> {
    const path = everywhere ? 'logout-all' : 'logout';
    return this.http.post(`/api/auth/${path}`, {}, { responseType: 'text' }).pipe(
      tap(() => this.clear()),
      map(() => undefined),
    );
  }

  clear(): void {
    this.user.set(null);
  }

  updateProfile(body: {
    account_name?: string;
    theme?: ThemePreference;
    safety_minimum?: string;
    debt_strategy?: DebtStrategy;
  }): Observable<User> {
    return this.http.patch<User>('/api/profile', body).pipe(tap((u) => this.accept(u)));
  }

  changePassword(body: { current_password: string | null; new_password: string }): Observable<User> {
    return this.http.post<User>('/api/profile/password', body).pipe(tap((u) => this.accept(u)));
  }
}
