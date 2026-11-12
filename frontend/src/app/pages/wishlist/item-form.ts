import { Component, OnInit, computed, inject, input, output, signal, viewChild } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FinanceService } from '../../core/finance.service';
import { moneyToInput, parseMoney } from '../../core/format';
import { apiMessage } from '../../core/http';
import { Category, WishlistItem } from '../../core/models';
import { Dialog } from '../../shared/dialog';

const MAX_IMAGE_BYTES = 2 * 1024 * 1024;

@Component({
  selector: 'app-wishlist-item-form',
  imports: [ReactiveFormsModule, Dialog],
  template: `
    <app-dialog [heading]="item() ? 'Editar item' : 'Novo item'" (closed)="closed.emit()">
      <form [formGroup]="form" (ngSubmit)="save()" novalidate>
        <div class="mb-3">
          <label class="form-label" for="wl-name">Nome</label>
          <input id="wl-name" class="form-control" formControlName="name" maxlength="120" />
        </div>
        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="wl-price">Preço estimado</label>
            <input id="wl-price" class="form-control money" formControlName="price"
                   inputmode="decimal" placeholder="0,00" autocomplete="off" />
          </div>
          <div>
            <label class="form-label" for="wl-category">Categoria</label>
            <select id="wl-category" class="form-select" formControlName="category_id">
              <option value="">Sem categoria</option>
              @for (c of categories(); track c.id) { <option [value]="c.id">{{ c.name }}</option> }
            </select>
          </div>
          <div>
            <label class="form-label" for="wl-priority">Prioridade</label>
            <select id="wl-priority" class="form-select" formControlName="priority">
              <option [ngValue]="1">Alta</option>
              <option [ngValue]="2">Média</option>
              <option [ngValue]="3">Baixa</option>
            </select>
          </div>
          @if (isOpen()) {
            <div>
              <label class="form-label" for="wl-status">Situação</label>
              <select id="wl-status" class="form-select" formControlName="status">
                <option value="desired">Desejado</option>
                <option value="planning">Planejando</option>
                <option value="saving">Economizando</option>
              </select>
            </div>
          }
        </div>
        <div class="mb-3">
          <label class="form-label" for="wl-store">Link da loja (opcional)</label>
          <input id="wl-store" class="form-control" type="url" formControlName="store_url" placeholder="https://" />
        </div>
        <div class="photo mb-3">
          <div class="preview" aria-hidden="true">
            @if (preview(); as src) { <img [src]="src" alt="" referrerpolicy="no-referrer" /> }
            @else { <i class="bi bi-image"></i> }
          </div>
          <div class="photo-fields">
            <label class="form-label" for="wl-image">Foto (opcional)</label>
            <input id="wl-image" class="form-control" type="file" accept="image/png,image/jpeg,image/webp"
                   (change)="pickFile($event)" />
            <p class="subtle mt-1 mb-0">
              @if (pasted()) { Imagem colada. }
              @else { Dica: na loja, clique com o botão direito na foto, escolha "Copiar imagem" e aperte Ctrl+V aqui. }
              Sem foto, buscamos pelo link da loja.
            </p>
          </div>
        </div>
        <div class="mb-3">
          <label class="form-label" for="wl-image-url">Endereço da imagem (opcional)</label>
          <input id="wl-image-url" class="form-control" type="url" formControlName="image_url" placeholder="https://" />
        </div>

        <h3 class="sub">Meta de economia</h3>
        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="wl-target">Meta (padrão: o preço)</label>
            <input id="wl-target" class="form-control money" formControlName="target_amount"
                   inputmode="decimal" placeholder="Igual ao preço" autocomplete="off" />
          </div>
          <div>
            <label class="form-label" for="wl-monthly">Guardar por mês (opcional)</label>
            <input id="wl-monthly" class="form-control money" formControlName="monthly_amount"
                   inputmode="decimal" placeholder="0,00" autocomplete="off" />
          </div>
          <div>
            <label class="form-label" for="wl-date">Data desejada (opcional)</label>
            <input id="wl-date" class="form-control" type="date" formControlName="target_date" />
          </div>
        </div>
        <div class="mb-3">
          <label class="form-label" for="wl-notes">Observações</label>
          <textarea id="wl-notes" class="form-control" rows="2" formControlName="notes" maxlength="2000"></textarea>
        </div>
        @if (error()) { <p class="field-error mb-2" role="alert">{{ error() }}</p> }
        <button type="submit" class="btn btn-brand w-100" [disabled]="busy()">
          {{ busy() ? 'Salvando…' : 'Salvar' }}
        </button>
      </form>
    </app-dialog>
  `,
  styles: `
    .sub { font-size: 0.875rem; font-weight: 600; margin: 0 0 0.5rem; }
    .photo { display: flex; gap: 0.75rem; align-items: flex-start; }
    .photo-fields { flex: 1; min-width: 0; }
    .preview {
      width: 4.5rem; height: 4.5rem; flex: none; border-radius: 0.5rem; overflow: hidden;
      display: grid; place-items: center; background: var(--surface-2, rgba(127, 127, 127, 0.1));
      color: var(--muted, inherit); font-size: 1.5rem;
    }
    .preview img { width: 100%; height: 100%; object-fit: contain; background: #fff; }
  `,
  host: { '(document:paste)': 'paste($event)' },
})
export class WishlistItemForm implements OnInit {
  private readonly finance = inject(FinanceService);

  readonly item = input<WishlistItem | null>(null);
  readonly closed = output<void>();

  private readonly dialog = viewChild.required(Dialog);
  private file: File | null = null;
  /** Depois do primeiro salvar, novas tentativas editam o mesmo item em vez de criar outro. */
  private savedId: string | null = null;
  protected readonly preview = signal<string | null>(null);
  protected readonly pasted = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly isOpen = computed(() => {
    const status = this.item()?.status;
    return status !== 'bought' && status !== 'given_up';
  });
  private readonly allCategories = toSignal(this.finance.categories(), { initialValue: [] as Category[] });
  protected readonly categories = computed(() =>
    this.allCategories().filter((c) => c.kind === 'expense'),
  );

  protected readonly form = new FormGroup({
    name: new FormControl('', { nonNullable: true }),
    price: new FormControl('', { nonNullable: true }),
    category_id: new FormControl('', { nonNullable: true }),
    priority: new FormControl(2, { nonNullable: true }),
    status: new FormControl('desired', { nonNullable: true }),
    store_url: new FormControl('', { nonNullable: true }),
    image_url: new FormControl('', { nonNullable: true }),
    target_amount: new FormControl('', { nonNullable: true }),
    monthly_amount: new FormControl('', { nonNullable: true }),
    target_date: new FormControl('', { nonNullable: true }),
    notes: new FormControl('', { nonNullable: true }),
  });

  ngOnInit(): void {
    const item = this.item();
    if (item) {
      this.form.patchValue({
        name: item.name,
        price: moneyToInput(item.price),
        category_id: item.category_id ?? '',
        priority: item.priority,
        status: item.status,
        store_url: item.store_url ?? '',
        image_url: item.image_url ?? '',
        target_amount: moneyToInput(item.target_amount),
        monthly_amount: moneyToInput(item.monthly_amount),
        target_date: item.target_date ?? '',
        notes: item.notes ?? '',
      });
      this.preview.set(item.has_upload ? `/api/wishlist/${item.id}/image` : item.image_url);
    }
  }

  protected pickFile(event: Event): void {
    this.useFile((event.target as HTMLInputElement).files?.[0] ?? null);
    this.pasted.set(false);
  }

  /** Imagem copiada da loja e colada com Ctrl+V. Texto colado nos campos segue normal. */
  protected paste(event: ClipboardEvent): void {
    const file = Array.from(event.clipboardData?.files ?? []).find((f) => f.type.startsWith('image/'));
    if (!file) return;
    event.preventDefault();
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
      this.error.set('Use uma imagem PNG, JPEG ou WEBP.');
      return;
    }
    if (this.useFile(file)) this.pasted.set(true);
  }

  private useFile(file: File | null): boolean {
    const tooBig = !!file && file.size > MAX_IMAGE_BYTES;
    this.error.set(tooBig ? 'A imagem precisa ter até 2 MB.' : null);
    if (tooBig) return false;
    this.file = file;
    if (file) {
      // data: em vez de blob:, que a política de segurança do app não libera para imagens.
      const reader = new FileReader();
      reader.onload = () => this.preview.set(reader.result as string);
      reader.readAsDataURL(file);
    }
    return true;
  }

  protected save(): void {
    if (this.busy()) return;
    this.error.set(null);
    const value = this.form.getRawValue();
    const price = parseMoney(value.price);
    const target = value.target_amount.trim() ? parseMoney(value.target_amount) : price;
    const monthly = value.monthly_amount.trim() ? parseMoney(value.monthly_amount) : '';
    if (!value.name.trim()) {
      this.error.set('Informe o nome.');
      return;
    }
    if (!price || Number(price) <= 0 || !target || Number(target) <= 0 || monthly === null) {
      this.error.set('Confira os valores informados, como 1.500,00.');
      return;
    }
    const item = this.item();
    const body = {
      name: value.name.trim(),
      price,
      category_id: value.category_id || null,
      priority: value.priority,
      store_url: value.store_url.trim() || null,
      image_url: value.image_url.trim() || null,
      target_amount: target,
      monthly_amount: monthly || null,
      target_date: value.target_date || null,
      notes: value.notes || null,
      ...(this.isOpen() ? { status: value.status } : {}),
    };
    this.busy.set(true);
    const retry = this.savedId !== null;
    this.finance.saveWishlistItem(body, item?.id ?? this.savedId ?? undefined).subscribe({
      next: (saved) => {
        this.savedId = saved.id;
        if (this.file) {
          this.finance.uploadWishlistImage(saved.id, this.file).subscribe({
            next: () => this.dialog().close(),
            error: (e) => this.fail(e, 'O item foi salvo, mas a imagem não.'),
          });
          return;
        }
        // Já avisamos que a foto não veio: salvar de novo sem imagem apenas fecha.
        if (retry || !this.shouldFetch(item, body.image_url, body.store_url)) {
          this.dialog().close();
          return;
        }
        this.finance.fetchWishlistImage(saved.id).subscribe({
          next: () => this.dialog().close(),
          error: (e) => {
            const reason = apiMessage(e, 'Não foi possível buscar a foto.');
            this.error.set(`Item salvo, mas a foto não veio. ${reason}`);
            this.busy.set(false);
          },
        });
      },
      error: (e) => this.fail(e, 'Não foi possível salvar.'),
    });
  }

  /** Item novo com algum link, ou links alterados na edição. Editar só o resto não busca de novo. */
  private shouldFetch(before: WishlistItem | null, imageUrl: string | null, storeUrl: string | null): boolean {
    if (!before) return !!(imageUrl || storeUrl);
    if (imageUrl && imageUrl !== before.image_url) return true;
    return !imageUrl && !before.has_upload && !!storeUrl && storeUrl !== before.store_url;
  }

  private fail(e: unknown, fallback: string): void {
    this.error.set(apiMessage(e, fallback));
    this.busy.set(false);
  }
}
