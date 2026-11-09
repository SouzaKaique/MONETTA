import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { apiMessage } from '../../core/http';
import { Providers, ThemePreference } from '../../core/models';
import { Avatar } from '../../layout/avatar';

const LINK_ERRORS: Record<string, string> = {
  cancelado: 'Vínculo cancelado.',
  sessao_expirada: 'A tentativa expirou. Tente novamente.',
  provedor: 'Não foi possível falar com o provedor. Tente novamente.',
  token_invalido: 'Não foi possível confirmar sua identidade. Tente novamente.',
  ja_vinculado: 'Esta conta do provedor já está ligada a outro usuário do MONETTA, ou você já vinculou outra.',
};
const PROVIDER_LABELS = { google: 'Google', apple: 'Apple' } as const;

@Component({
  selector: 'app-profile',
  imports: [ReactiveFormsModule, Avatar],
  templateUrl: './profile.html',
  styleUrl: './profile.css',
})
export class ProfilePage implements OnInit {
  protected readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly providers = signal<Providers | null>(null);
  protected readonly linkError = signal<string | null>(null);
  protected readonly linkMessage = signal<string | null>(null);

  /** Provedores configurados neste servidor, com o estado de vínculo da conta. */
  protected readonly socialRows = computed(() => {
    const user = this.auth.user();
    const enabled = this.providers();
    if (!user || !enabled) return [];
    return (['google', 'apple'] as const)
      .filter((key) => enabled[key])
      .map((key) => ({
        key,
        label: PROVIDER_LABELS[key],
        icon: key === 'google' ? 'bi-google' : 'bi-apple',
        linked: user.providers.includes(key),
      }));
  });

  ngOnInit(): void {
    this.auth.providers().subscribe({ next: (p) => this.providers.set(p), error: () => {} });
    const query = this.route.snapshot.queryParamMap;
    const linked = query.get('vinculado') as keyof typeof PROVIDER_LABELS | null;
    const failed = query.get('erro');
    if (linked && PROVIDER_LABELS[linked]) {
      this.linkMessage.set(`${PROVIDER_LABELS[linked]} vinculado. Agora você também pode entrar por ele.`);
    } else if (failed) {
      this.linkError.set(LINK_ERRORS[failed] ?? 'Não foi possível vincular.');
    }
    if (linked || failed) {
      void this.auth.ensureLoaded();
      void this.router.navigate([], { queryParams: {}, replaceUrl: true });
    }
  }

  protected link(provider: 'google' | 'apple'): void {
    this.linkError.set(null);
    this.auth.linkSocial(provider).subscribe({
      next: (url) => location.assign(url),
      error: (e) => this.linkError.set(apiMessage(e, 'Não foi possível iniciar o vínculo.')),
    });
  }

  protected unlink(provider: 'google' | 'apple'): void {
    this.linkError.set(null);
    this.linkMessage.set(null);
    this.auth.unlinkSocial(provider).subscribe({
      next: () => this.linkMessage.set(`${PROVIDER_LABELS[provider]} desvinculado.`),
      error: (e) => this.linkError.set(apiMessage(e, 'Não foi possível desvincular.')),
    });
  }

  protected readonly themes: { value: ThemePreference; label: string; icon: string }[] = [
    { value: 'system', label: 'Sistema', icon: 'bi-circle-half' },
    { value: 'light', label: 'Claro', icon: 'bi-sun' },
    { value: 'dark', label: 'Escuro', icon: 'bi-moon' },
  ];

  protected readonly methods = computed(() => {
    const user = this.auth.user();
    if (!user) return [];
    return [
      ...(user.has_password ? [{ label: 'E-mail e senha', icon: 'bi-envelope' }] : []),
      ...(user.providers.includes('google') ? [{ label: 'Google', icon: 'bi-google' }] : []),
      ...(user.providers.includes('apple') ? [{ label: 'Apple', icon: 'bi-apple' }] : []),
    ];
  });

  protected readonly nameSaved = signal(false);
  protected readonly nameError = signal<string | null>(null);
  protected readonly passwordMessage = signal<string | null>(null);
  protected readonly passwordError = signal<string | null>(null);
  protected readonly themeError = signal<string | null>(null);

  protected readonly name = new FormControl(this.auth.user()?.account_name ?? '', {
    nonNullable: true,
    validators: [Validators.required, Validators.minLength(2), Validators.maxLength(80)],
  });

  protected readonly password = new FormGroup({
    current_password: new FormControl('', { nonNullable: true }),
    new_password: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.minLength(10)],
    }),
  });

  protected saveName(): void {
    this.nameSaved.set(false);
    this.nameError.set(null);
    if (this.name.invalid) {
      this.nameError.set('Use de 2 a 80 caracteres.');
      return;
    }
    this.auth.updateProfile({ account_name: this.name.value.trim() }).subscribe({
      next: () => this.nameSaved.set(true),
      error: (e) => this.nameError.set(apiMessage(e, 'Não foi possível salvar.')),
    });
  }

  protected setTheme(theme: ThemePreference): void {
    this.themeError.set(null);
    this.auth.updateProfile({ theme }).subscribe({
      error: (e) => this.themeError.set(apiMessage(e, 'Não foi possível salvar o tema.')),
    });
  }

  protected savePassword(): void {
    this.passwordMessage.set(null);
    this.passwordError.set(null);
    if (this.password.invalid) {
      this.passwordError.set('A nova senha precisa de pelo menos 10 caracteres.');
      return;
    }
    const { current_password, new_password } = this.password.getRawValue();
    const hadPassword = this.auth.user()?.has_password;
    this.auth
      .changePassword({ current_password: hadPassword ? current_password : null, new_password })
      .subscribe({
        next: () => {
          this.password.reset();
          this.passwordMessage.set(
            hadPassword ? 'Senha alterada. As outras sessões foram encerradas.' : 'Senha criada.',
          );
        },
        error: (e) => this.passwordError.set(apiMessage(e, 'Não foi possível salvar a senha.')),
      });
  }

  protected logout(everywhere = false): void {
    this.auth.logout(everywhere).subscribe(() => void this.router.navigateByUrl('/login'));
  }
}
