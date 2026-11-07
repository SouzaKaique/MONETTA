import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormControl, FormGroup, FormsModule, ReactiveFormsModule } from '@angular/forms';
import { AuthService } from '../../core/auth.service';
import { FinanceService } from '../../core/finance.service';
import { formatDate, formatMoney, moneyToInput, parseMoney, todayIso } from '../../core/format';
import { apiMessage } from '../../core/http';
import { Account, Category, Kind, Transfer } from '../../core/models';
import { Dialog } from '../../shared/dialog';

const ACCOUNT_TYPES: Record<string, string> = {
  checking: 'Conta corrente', savings: 'Poupança', cash: 'Dinheiro',
};

@Component({
  selector: 'app-settings',
  imports: [ReactiveFormsModule, FormsModule, Dialog],
  templateUrl: './settings.html',
  styleUrl: './settings.css',
})
export class SettingsPage {
  private readonly finance = inject(FinanceService);
  private readonly auth = inject(AuthService);

  protected readonly types = Object.entries(ACCOUNT_TYPES);
  protected readonly typeLabel = ACCOUNT_TYPES;
  protected readonly money = formatMoney;
  protected readonly date = formatDate;
  protected readonly today = todayIso();

  protected readonly accounts = signal<Account[]>([]);
  protected readonly categories = signal<Category[]>([]);
  protected readonly transfers = signal<Transfer[]>([]);
  protected readonly activeAccounts = computed(() => this.accounts().filter((a) => a.active));

  protected readonly error = signal<string | null>(null);
  protected readonly formError = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly deleting = signal<string | null>(null);

  protected readonly safety = new FormControl(
    moneyToInput(this.auth.user()?.safety_minimum), { nonNullable: true },
  );
  protected readonly safetySaved = signal(false);

  // Alertas
  protected readonly alertKinds = [
    { value: 'budget', label: 'Orçamento' },
    { value: 'card', label: 'Cartões e faturas' },
    { value: 'debt', label: 'Dívidas' },
    { value: 'balance', label: 'Saldo e comprometimento' },
    { value: 'insight', label: 'Sugestões e variações de gastos' },
    { value: 'recovery', label: 'Modo Recuperação' },
    { value: 'wishlist', label: 'Metas da wishlist' },
  ];
  protected readonly muted = signal<string[]>(this.auth.user()?.alert_prefs.muted ?? []);
  protected readonly alertsSaved = signal(false);
  protected readonly alertForm = new FormGroup({
    budget_pct: new FormControl(this.auth.user()?.alert_prefs.budget_pct ?? 80, { nonNullable: true }),
    card_pct: new FormControl(this.auth.user()?.alert_prefs.card_pct ?? 80, { nonNullable: true }),
    commitment_pct: new FormControl(this.auth.user()?.alert_prefs.commitment_pct ?? 80, { nonNullable: true }),
    due_days: new FormControl(this.auth.user()?.alert_prefs.due_days ?? 3, { nonNullable: true }),
  });

  // Conta
  protected readonly accountDialog = signal(false);
  protected readonly editingAccount = signal<Account | null>(null);
  protected readonly accountForm = new FormGroup({
    name: new FormControl('', { nonNullable: true }),
    type: new FormControl('checking', { nonNullable: true }),
    opening_balance: new FormControl('', { nonNullable: true }),
    opening_date: new FormControl(this.today, { nonNullable: true }),
    real_balance: new FormControl('', { nonNullable: true }),
  });

  // Transferência
  protected readonly transferDialog = signal(false);
  protected readonly transferForm = new FormGroup({
    from_account_id: new FormControl('', { nonNullable: true }),
    to_account_id: new FormControl('', { nonNullable: true }),
    amount: new FormControl('', { nonNullable: true }),
    date: new FormControl(this.today, { nonNullable: true }),
  });

  // Categoria
  protected readonly categoryKind = signal<Kind>('expense');
  protected readonly visibleCategories = computed(() =>
    this.categories().filter((c) => c.kind === this.categoryKind()),
  );
  protected readonly newCategory = new FormControl('', { nonNullable: true });
  protected readonly renaming = signal<string | null>(null);
  protected renameValue = '';

  constructor() {
    effect(() => {
      this.finance.revision();
      untracked(() => this.load());
    });
  }

  private load(): void {
    const fail = (e: unknown) => this.error.set(apiMessage(e, 'Não foi possível carregar.'));
    this.finance.accounts().subscribe({ next: (a) => this.accounts.set(a), error: fail });
    this.finance.categories().subscribe({ next: (c) => this.categories.set(c), error: fail });
    this.finance.transfers().subscribe({ next: (t) => this.transfers.set(t), error: fail });
  }

  protected saveSafety(): void {
    this.safetySaved.set(false);
    this.error.set(null);
    const value = this.safety.value.trim() === '' ? '0' : parseMoney(this.safety.value);
    if (value === null || Number(value) < 0) {
      this.error.set('Informe um valor mínimo válido, como 500,00.');
      return;
    }
    this.auth.updateProfile({ safety_minimum: value }).subscribe({
      next: () => {
        this.safetySaved.set(true);
        this.finance.revision.update((v) => v + 1);
      },
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível salvar.')),
    });
  }

  protected toggleMuted(kind: string): void {
    this.muted.update((all) => (all.includes(kind) ? all.filter((k) => k !== kind) : [...all, kind]));
  }

  protected saveAlerts(): void {
    this.error.set(null);
    this.alertsSaved.set(false);
    this.auth.updateProfile({
      alert_prefs: { ...this.alertForm.getRawValue(), muted: this.muted() },
    }).subscribe({
      next: () => {
        this.alertsSaved.set(true);
        this.finance.revision.update((v) => v + 1);
      },
      error: (e) => this.error.set(apiMessage(e, 'Confira os valores dos alertas.')),
    });
  }

  protected toggleEssential(category: Category): void {
    this.finance.saveCategory({ is_essential: !category.is_essential }, category.id).subscribe({
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível alterar.')),
    });
  }

  protected openAccount(account: Account | null): void {
    this.formError.set(null);
    this.editingAccount.set(account);
    this.accountForm.reset({
      name: account?.name ?? '',
      type: account?.type ?? 'checking',
      opening_balance: moneyToInput(account?.opening_balance),
      opening_date: account?.opening_date ?? this.today,
      real_balance: moneyToInput(account?.real_balance),
    });
    this.accountDialog.set(true);
  }

  protected saveAccount(dialog: Dialog): void {
    this.formError.set(null);
    const value = this.accountForm.getRawValue();
    const opening = value.opening_balance.trim() === '' ? '0' : parseMoney(value.opening_balance);
    const realText = value.real_balance.trim();
    const real = realText === '' ? null : parseMoney(realText);
    if (!value.name.trim()) {
      this.formError.set('Informe o nome da conta.');
      return;
    }
    if (opening === null || (realText !== '' && real === null)) {
      this.formError.set('Informe valores válidos, como 1.500,00.');
      return;
    }
    const editing = this.editingAccount();
    const body = {
      name: value.name.trim(),
      type: value.type as Account['type'],
      opening_balance: opening,
      opening_date: value.opening_date,
      ...(editing ? { real_balance: real } : {}),
    };
    this.busy.set(true);
    this.finance.saveAccount(body, editing?.id).subscribe({
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

  protected toggleAccount(account: Account): void {
    this.finance.saveAccount({ active: !account.active }, account.id).subscribe({
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível alterar.')),
    });
  }

  protected deleteAccount(account: Account): void {
    this.error.set(null);
    this.finance.deleteAccount(account.id).subscribe({
      next: () => this.deleting.set(null),
      error: (e) => {
        this.deleting.set(null);
        this.error.set(apiMessage(e, 'Não foi possível excluir.'));
      },
    });
  }

  protected openTransfer(): void {
    this.formError.set(null);
    this.transferForm.reset({ date: this.today, from_account_id: '', to_account_id: '', amount: '' });
    this.transferDialog.set(true);
  }

  protected saveTransfer(dialog: Dialog): void {
    this.formError.set(null);
    const value = this.transferForm.getRawValue();
    const amount = parseMoney(value.amount);
    if (!value.from_account_id || !value.to_account_id) {
      this.formError.set('Escolha as duas contas.');
      return;
    }
    if (!amount || Number(amount) <= 0) {
      this.formError.set('Informe um valor válido, como 89,90.');
      return;
    }
    this.busy.set(true);
    this.finance.createTransfer({ ...value, amount }).subscribe({
      next: () => {
        this.busy.set(false);
        dialog.close();
      },
      error: (e) => {
        this.busy.set(false);
        this.formError.set(apiMessage(e, 'Não foi possível transferir.'));
      },
    });
  }

  protected deleteTransfer(transfer: Transfer): void {
    this.finance.deleteTransfer(transfer.id).subscribe({
      next: () => this.deleting.set(null),
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível excluir.')),
    });
  }

  protected addCategory(): void {
    this.error.set(null);
    const name = this.newCategory.value.trim();
    if (!name) return;
    this.finance.saveCategory({ name, kind: this.categoryKind() }).subscribe({
      next: () => this.newCategory.reset(),
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível criar.')),
    });
  }

  protected startRename(category: Category): void {
    this.renaming.set(category.id);
    this.renameValue = category.name;
  }

  protected rename(category: Category): void {
    const name = this.renameValue.trim();
    if (!name || name === category.name) {
      this.renaming.set(null);
      return;
    }
    this.finance.saveCategory({ name }, category.id).subscribe({
      next: () => this.renaming.set(null),
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível renomear.')),
    });
  }

  protected deleteCategory(category: Category): void {
    this.error.set(null);
    this.finance.deleteCategory(category.id).subscribe({
      next: () => this.deleting.set(null),
      error: (e) => {
        this.deleting.set(null);
        this.error.set(apiMessage(e, 'Não foi possível excluir.'));
      },
    });
  }
}
