import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { AuthService } from './auth.service';

/** Header anti-CSRF exigido pela API; se a sessão cair, volta para o login. */
export const apiInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const request = req.url.startsWith('/api/')
    ? req.clone({ setHeaders: { 'X-Monetta-Client': 'web' } })
    : req;

  return next(request).pipe(
    catchError((error: HttpErrorResponse) => {
      const sessionCall = req.url.startsWith('/api/auth/');
      if (error.status === 401 && !sessionCall && auth.isLoggedIn()) {
        auth.clear();
        void router.navigateByUrl('/login');
      }
      return throwError(() => error);
    }),
  );
};

export const authGuard: CanActivateFn = async () => {
  // inject() só funciona antes do primeiro await.
  const auth = inject(AuthService);
  const router = inject(Router);
  return (await auth.ensureLoaded()) ? true : router.createUrlTree(['/login']);
};

export function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof HttpErrorResponse && error.status === 0) {
    return 'Não foi possível falar com o servidor.';
  }
  const body = (error as HttpErrorResponse)?.error;
  // Erro de validação: a mensagem do campo diz mais do que "Dados inválidos".
  const fieldMessages = body?.fields ? Object.values(body.fields).flat() : [];
  if (typeof fieldMessages[0] === 'string') return fieldMessages[0];
  return typeof body?.error === 'string' ? body.error : fallback;
}
