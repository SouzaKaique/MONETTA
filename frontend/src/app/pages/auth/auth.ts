import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { apiMessage } from '../../core/http';
import { Providers } from '../../core/models';

const SOCIAL_ERRORS: Record<string, string> = {
  cancelado: 'Login cancelado.',
  sessao_expirada: 'A tentativa de login expirou. Tente novamente.',
  provedor: 'Não foi possível concluir o login com o provedor. Tente novamente.',
  token_invalido: 'Não foi possível confirmar sua identidade. Tente novamente.',
  email_nao_verificado: 'Sua conta no provedor não tem um e-mail verificado.',
  conta_existente: 'Já existe uma conta com este e-mail. Entre com sua senha.',
  cadastro_fechado: 'O cadastro de novas contas está fechado.',
};

@Component({
  selector: 'app-auth',
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './auth.html',
  styleUrl: './auth.css',
})
export class AuthPage implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly mode = signal<'login' | 'register'>(this.route.snapshot.data['mode']);
  protected readonly isRegister = computed(() => this.mode() === 'register');
  protected readonly providers = signal<Providers | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly submitted = signal(false);
  protected readonly showPassword = signal(false);

  protected readonly form = new FormGroup({
    account_name: new FormControl('', { nonNullable: true }),
    email: new FormControl('', { nonNullable: true, validators: [Validators.required, Validators.email] }),
    password: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
  });

  async ngOnInit(): Promise<void> {
    if (await this.auth.ensureLoaded()) {
      void this.router.navigateByUrl('/');
      return;
    }
    const code = this.route.snapshot.queryParamMap.get('erro');
    if (code) this.error.set(SOCIAL_ERRORS[code] ?? 'Não foi possível entrar.');

    if (this.isRegister()) {
      this.form.controls.account_name.addValidators([Validators.required, Validators.minLength(2)]);
      this.form.controls.password.addValidators(Validators.minLength(10));
      this.form.controls.account_name.updateValueAndValidity();
      this.form.controls.password.updateValueAndValidity();
    }
    this.auth.providers().subscribe({
      next: (p) => this.providers.set(p),
      error: () => this.providers.set({ google: false, apple: false, registration: false }),
    });
  }

  protected invalid(name: 'account_name' | 'email' | 'password'): boolean {
    return this.submitted() && this.form.controls[name].invalid;
  }

  protected social(provider: 'google' | 'apple'): void {
    this.auth.startSocial(provider);
  }

  protected submit(): void {
    this.submitted.set(true);
    this.error.set(null);
    if (this.form.invalid || this.busy()) return;

    this.busy.set(true);
    const { account_name, email, password } = this.form.getRawValue();
    const request = this.isRegister()
      ? this.auth.register({ account_name: account_name.trim(), email, password })
      : this.auth.login({ email, password });

    request.subscribe({
      next: () => void this.router.navigateByUrl('/'),
      error: (e) => {
        this.error.set(apiMessage(e, 'Não foi possível continuar. Tente novamente.'));
        this.busy.set(false);
      },
    });
  }
}
