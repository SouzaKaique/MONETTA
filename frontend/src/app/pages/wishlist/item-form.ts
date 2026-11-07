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
        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="wl-image-url">Endereço da imagem (opcional)</label>
            <input id="wl-image-url" class="form-control" type="url" formControlName="image_url" placeholder="https://" />
          </div>
          <div>
            <label class="form-label" for="wl-image">Ou envie uma imagem</label>
            <input id="wl-image" class="form-control" type="file" accept="image/png,image/jpeg,image/webp"
                   (change)="pickFile($event)" />
          </div>
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
  styles: `.sub { font-size: 0.875rem; font-weight: 600; margin: 0 0 0.5rem; }`,
})
export class WishlistItemForm implements OnInit {
  private readonly finance = inject(FinanceService);

  readonly item = input<WishlistItem | null>(null);
  readonly closed = output<void>();

  private readonly dialog = viewChild.required(Dialog);
  private file: File | null = null;
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
    }
  }

  protected pickFile(event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0] ?? null;
    this.error.set(file && file.size > MAX_IMAGE_BYTES ? 'A imagem precisa ter até 2 MB.' : null);
    this.file = file && file.size <= MAX_IMAGE_BYTES ? file : null;
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
    this.finance.saveWishlistItem(body, item?.id).subscribe({
      next: (saved) => {
        if (!this.file) {
          this.dialog().close();
          return;
        }
        this.finance.uploadWishlistImage(saved.id, this.file).subscribe({
          next: () => this.dialog().close(),
          error: (e) => this.fail(e, 'O item foi salvo, mas a imagem não.'),
        });
      },
      error: (e) => this.fail(e, 'Não foi possível salvar.'),
    });
  }

  private fail(e: unknown, fallback: string): void {
    this.error.set(apiMessage(e, fallback));
    this.busy.set(false);
  }
}
