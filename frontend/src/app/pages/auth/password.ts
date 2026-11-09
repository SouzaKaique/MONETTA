import { Component, OnInit, inject, signal } from '@angular/core';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { apiMessage } from '../../core/http';

/** "Esqueci minha senha" e a tela aberta pelo link recebido no e-mail. */
@Component({
  selector: 'app-password',
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './password.html',
  styleUrl: './auth.css',
})
export class PasswordPage implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly route = inject(ActivatedRoute);

  protected readonly mode: 'forgot' | 'reset' = this.route.snapshot.data['mode'];
  protected readonly busy = signal(false);
  protected readonly submitted = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly done = signal<string | null>(null);
  protected readonly showPassword = signal(false);
  private token = '';

  protected readonly email = new FormControl('', {
    nonNullable: true,
    validators: [Validators.required, Validators.email],
  });
  protected readonly password = new FormControl('', {
    nonNullable: true,
    validators: [Validators.required, Validators.minLength(10)],
  });

  ngOnInit(): void {
    if (this.mode !== 'reset') return;
    // O código vem depois do #: o navegador não o envia ao servidor nem ao histórico de acessos.
    this.token = this.route.snapshot.fragment ?? '';
    history.replaceState(null, '', location.pathname);
    if (!this.token) this.error.set('Link incompleto. Abra de novo o link do e-mail ou peça outro.');
  }

  protected submit(): void {
    this.submitted.set(true);
    this.error.set(null);
    if (this.busy()) return;
    const request =
      this.mode === 'forgot'
        ? this.email.invalid ? null : this.auth.forgotPassword(this.email.value.trim())
        : this.password.invalid || !this.token ? null : this.auth.resetPassword(this.token, this.password.value);
    if (!request) return;

    this.busy.set(true);
    request.subscribe({
      next: (message) => {
        this.done.set(message);
        this.busy.set(false);
      },
      error: (e) => {
        this.error.set(apiMessage(e, 'Não foi possível continuar. Tente novamente.'));
        this.busy.set(false);
      },
    });
  }
}
