import { Component, computed, inject, input, output, signal, viewChild } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FinanceService } from '../../core/finance.service';
import { formatDate, formatMoney, formatMonth } from '../../core/format';
import { apiMessage } from '../../core/http';
import { Category, ImportPreview, ImportRow, ImportStatus } from '../../core/models';
import { Dialog } from '../../shared/dialog';

const LABELS: Record<ImportStatus, string> = {
  new: 'Nova',
  existing: 'Já lançada',
  fixed: 'Gasto fixo',
  included: 'Já somado',
  imported: 'Já importada',
  payment: 'Pagamento',
  credit: 'Crédito',
};

/** Lê o arquivo da fatura (OFX ou CSV do Nubank), mostra a prévia e importa o que for novo. */
@Component({
  selector: 'app-import-bill',
  imports: [Dialog],
  template: `
    <app-dialog heading="Importar fatura" [wide]="true" (closed)="closed.emit()">
      @if (!preview()) {
        <p class="subtle">
          No app do Nubank, abra a fatura, toque no ícone de compartilhar e exporte em <strong>OFX</strong>
          (ou CSV). Envie o arquivo aqui: antes de gravar, você confere o que é novo e o que já está no MONETTA.
        </p>
        <label class="form-label" for="ib-file">Arquivo da fatura</label>
        <input id="ib-file" class="form-control mb-3" type="file" accept=".ofx,.csv,.qfx,.txt"
               (change)="pick($event)" [disabled]="busy()" />
        @if (busy()) { <p class="subtle mb-0">Lendo o arquivo…</p> }
      } @else {
        @let p = preview()!;
        <div class="head">
          <div>
            <strong>Fatura de {{ monthLabel(p.month) }}</strong>
            <span class="subtle"> · vence {{ date(p.due_date) }}</span>
          </div>
          <label class="month">
            <span class="subtle">Outra fatura</span>
            <input class="form-control form-control-sm" type="month" [value]="p.month"
                   (change)="changeMonth($event)" [disabled]="busy()" />
          </label>
        </div>

        <dl class="totals">
          <div><dt>Compras no arquivo</dt><dd class="money">{{ money(p.file_total) }}</dd></div>
          <div><dt>No MONETTA agora</dt><dd class="money">{{ money(p.invoice_total) }}</dd></div>
          <div>
            <dt>Depois de importar</dt>
            <dd class="money" [class.ok]="matches()">
              {{ money(after()) }}
              @if (matches()) { <i class="bi bi-check-circle-fill" title="Igual ao banco" aria-label="Igual ao banco"></i> }
            </dd>
          </div>
        </dl>

        @if (fresh().length) {
          <h3 class="sub">Novas ({{ fresh().length }})</h3>
          <ul class="lines">
            @for (r of fresh(); track r.external_id) {
              <li [class.off]="!chosen().has(r.external_id)">
                <input type="checkbox" class="form-check-input" [checked]="chosen().has(r.external_id)"
                       (change)="toggle(r)" [attr.aria-label]="'Importar ' + r.description" />
                <div class="what">
                  <strong>{{ r.description }}</strong>
                  <span class="subtle">
                    {{ date(r.date) }}
                    @if (r.count > 1) { · parcela {{ r.number }} de {{ r.count }} }
                  </span>
                </div>
                <select class="form-select form-select-sm" [value]="category(r)" (change)="setCategory(r, $event)"
                        [attr.aria-label]="'Categoria de ' + r.description">
                  <option value="">Sem categoria</option>
                  @for (c of categories(); track c.id) {
                    <option [value]="c.id" [selected]="c.id === category(r)">{{ c.name }}</option>
                  }
                </select>
                <span class="money amount">{{ money(r.amount) }}</span>
              </li>
            }
          </ul>
        } @else {
          <p class="notice-line"><i class="bi bi-check2-all" aria-hidden="true"></i> Nenhuma compra nova: tudo já está no MONETTA.</p>
        }

        @if (known().length) {
          <details>
            <summary>Já no MONETTA ({{ known().length }})</summary>
            <ul class="lines plain">
              @for (r of known(); track r.external_id) {
                <li>
                  <span class="tag">{{ labels[r.status] }}</span>
                  <div class="what">
                    <span>{{ r.description }} @if (r.count > 1) { <span class="subtle">· {{ r.number }}/{{ r.count }}</span> }</span>
                    @if (r.note) { <span class="subtle">{{ r.note }}</span> }
                  </div>
                  <span class="money amount">{{ money(r.amount) }}</span>
                </li>
              }
            </ul>
          </details>
        }

        @if (ignored().length) {
          <details>
            <summary>Não entram ({{ ignored().length }})</summary>
            <ul class="lines plain">
              @for (r of ignored(); track r.external_id) {
                <li>
                  <span class="tag">{{ labels[r.status] }}</span>
                  <div class="what"><span>{{ r.description }}</span><span class="subtle">{{ r.note }}</span></div>
                  <span class="money amount">{{ money(r.amount) }}</span>
                </li>
              }
            </ul>
          </details>
        }

        @if (p.missing.length) {
          <details open>
            <summary>Só no MONETTA ({{ p.missing.length }})</summary>
            <p class="subtle mb-1">Estão nesta fatura do MONETTA, mas não no arquivo: podem ainda não ter sido
              cobradas, ou foram lançadas a mais.</p>
            <ul class="lines plain">
              @for (m of p.missing; track m.installment_id) {
                <li>
                  @if (m.fixed) { <span class="tag">Gasto fixo</span> }
                  <div class="what">
                    <span>{{ m.description }} @if (m.count > 1) { <span class="subtle">· {{ m.number }}/{{ m.count }}</span> }</span>
                    <span class="subtle">{{ date(m.date) }}</span>
                  </div>
                  <span class="money amount">{{ money(m.amount) }}</span>
                </li>
              }
            </ul>
          </details>
        }

        @if (done()) {
          <p class="notice-line ok mt-3" role="status"><i class="bi bi-check-circle" aria-hidden="true"></i> {{ done() }}</p>
        }
        @if (error()) { <p class="field-error mt-3 mb-0" role="alert">{{ error() }}</p> }
        <div class="actions mt-3">
          <button type="button" class="btn btn-quiet" (click)="reset()" [disabled]="busy()">Outro arquivo</button>
          @if (!done()) {
            <button type="button" class="btn btn-brand" (click)="save()" [disabled]="busy() || !canSave()">
              {{ busy() ? 'Importando…' : saveLabel() }}
            </button>
          } @else {
            <button type="button" class="btn btn-brand" (click)="dialog().close()">Fechar</button>
          }
        </div>
      }
      @if (error() && !preview()) { <p class="field-error mb-0" role="alert">{{ error() }}</p> }
    </app-dialog>
  `,
  styles: `
    .head { align-items: end; display: flex; flex-wrap: wrap; gap: 0.75rem; justify-content: space-between; }
    .month { display: grid; gap: 0.2rem; font-size: 0.8rem; }
    .totals { display: grid; gap: 0.5rem; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 1rem 0; }
    .totals div { background: var(--surface-2); border-radius: var(--radius-sm); padding: 0.5rem 0.65rem; }
    .totals dt { color: var(--ink-3); font-size: 0.75rem; font-weight: 400; }
    .totals dd { font-weight: 600; margin: 0; }
    .totals dd.ok { color: var(--positive, inherit); }
    .sub { font-size: 0.875rem; font-weight: 600; margin: 0 0 0.4rem; }
    .lines { display: grid; gap: 0.15rem; list-style: none; margin: 0 0 0.75rem; padding: 0; }
    .lines li {
      align-items: center; border-bottom: 1px solid var(--border); display: grid; gap: 0.6rem;
      grid-template-columns: auto minmax(0, 1fr) minmax(120px, 170px) auto; padding: 0.4rem 0;
    }
    .lines.plain li { grid-template-columns: auto minmax(0, 1fr) auto; }
    .lines li.off { opacity: 0.5; }
    .what { display: grid; min-width: 0; }
    .what > * { overflow: hidden; text-overflow: ellipsis; }
    .what .subtle { font-size: 0.8rem; }
    .amount { text-align: right; white-space: nowrap; }
    details { border-top: 1px solid var(--border); padding: 0.5rem 0; }
    summary { cursor: pointer; font-size: 0.875rem; font-weight: 600; }
    .notice-line { color: var(--ink-2); font-size: 0.9rem; margin: 0.25rem 0 0.75rem; }
    .actions { display: flex; flex-wrap: wrap; gap: 0.5rem; justify-content: flex-end; }
    @media (max-width: 575.98px) {
      .totals { grid-template-columns: minmax(0, 1fr); }
      .lines li { grid-template-columns: auto minmax(0, 1fr) auto; }
      .lines li select { grid-column: 2 / 4; }
    }
  `,
})
export class ImportBill {
  private readonly finance = inject(FinanceService);

  readonly cardId = input.required<string>();
  readonly closed = output<void>();

  protected readonly dialog = viewChild.required(Dialog);
  protected readonly labels = LABELS;
  protected readonly money = formatMoney;
  protected readonly date = formatDate;
  protected readonly monthLabel = formatMonth;

  protected readonly preview = signal<ImportPreview | null>(null);
  protected readonly chosen = signal<Set<string>>(new Set());
  protected readonly categoryOf = signal<Record<string, string>>({});
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly done = signal<string | null>(null);
  private file: File | null = null;

  private readonly allCategories = toSignal(this.finance.categories(), { initialValue: [] as Category[] });
  protected readonly categories = computed(() => this.allCategories().filter((c) => c.kind === 'expense'));

  protected readonly fresh = computed(() => this.rows('new'));
  protected readonly known = computed(() => this.rows('existing', 'fixed', 'included', 'imported'));
  protected readonly ignored = computed(() => this.rows('payment', 'credit'));
  protected readonly links = computed(() =>
    (this.preview()?.rows ?? []).filter((r) => (r.status === 'existing' || r.status === 'fixed') && r.installment_id),
  );
  protected readonly after = computed(() => {
    const p = this.preview();
    if (!p) return '0';
    const chosen = this.chosen();
    const added = this.fresh().filter((r) => chosen.has(r.external_id)).reduce((s, r) => s + cents(r.amount), 0);
    // Ligar uma parcela pode corrigir centavos para o valor da fatura.
    const fixes = this.links().reduce((s, r) => s + (r.note?.startsWith('Valor ajustado') ? this.centsDiff(r) : 0), 0);
    return ((cents(p.invoice_total) + added + fixes) / 100).toFixed(2);
  });
  protected readonly matches = computed(() => {
    const p = this.preview();
    return !!p && cents(this.after()) === cents(p.file_total);
  });
  protected readonly canSave = computed(() => this.chosen().size > 0 || this.links().length > 0);
  protected readonly saveLabel = computed(() => {
    const n = this.chosen().size;
    if (n === 0) return 'Confirmar';
    return n === 1 ? 'Importar 1 compra' : `Importar ${n} compras`;
  });

  private rows(...statuses: ImportStatus[]): ImportRow[] {
    return (this.preview()?.rows ?? []).filter((r) => statuses.includes(r.status));
  }

  /** O valor antigo vem na nota ("Valor ajustado de R$ 47,77 ..."): só para mostrar o total certo. */
  private centsDiff(row: ImportRow): number {
    const old = row.note?.match(/R\$\s*([\d.]+,\d{2})/)?.[1];
    return old ? cents(row.amount) - cents(old.replace(/\./g, '').replace(',', '.')) : 0;
  }

  protected pick(event: Event): void {
    this.file = (event.target as HTMLInputElement).files?.[0] ?? null;
    if (this.file) this.load();
  }

  protected changeMonth(event: Event): void {
    const month = (event.target as HTMLInputElement).value;
    if (month) this.load(month);
  }

  private load(month?: string): void {
    if (!this.file) return;
    this.busy.set(true);
    this.error.set(null);
    this.finance.previewImport(this.cardId(), this.file, month).subscribe({
      next: (p) => {
        this.preview.set(p);
        this.chosen.set(new Set(p.rows.filter((r) => r.status === 'new').map((r) => r.external_id)));
        this.categoryOf.set({});
        this.busy.set(false);
      },
      error: (e) => {
        this.error.set(apiMessage(e, 'Não foi possível ler o arquivo.'));
        this.busy.set(false);
      },
    });
  }

  protected reset(): void {
    this.preview.set(null);
    this.done.set(null);
    this.error.set(null);
    this.file = null;
  }

  protected toggle(row: ImportRow): void {
    const next = new Set(this.chosen());
    if (next.has(row.external_id)) next.delete(row.external_id);
    else next.add(row.external_id);
    this.chosen.set(next);
  }

  protected category(row: ImportRow): string {
    return this.categoryOf()[row.external_id] ?? row.category_id ?? '';
  }

  protected setCategory(row: ImportRow, event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.categoryOf.update((all) => ({ ...all, [row.external_id]: value }));
  }

  protected save(): void {
    const p = this.preview();
    if (!p || this.busy()) return;
    const chosen = this.chosen();
    const body = {
      month: p.month,
      create: this.fresh().filter((r) => chosen.has(r.external_id)).map((r) => ({
        external_id: r.external_id, date: r.date, description: r.description, amount: r.amount,
        number: r.number, count: r.count, category_id: this.category(r) || null,
      })),
      link: this.links().map((r) => ({ external_id: r.external_id, installment_id: r.installment_id, amount: r.amount })),
    };
    this.busy.set(true);
    this.error.set(null);
    this.finance.confirmImport(this.cardId(), body).subscribe({
      next: (result) => {
        this.busy.set(false);
        const parts = [`${result.created} ${result.created === 1 ? 'compra importada' : 'compras importadas'}`];
        if (result.linked) parts.push(`${result.linked} ${result.linked === 1 ? 'ligada' : 'ligadas'} ao que já estava lançado`);
        this.done.set(parts.join(' e ') + '.');
      },
      error: (e) => {
        this.busy.set(false);
        this.error.set(apiMessage(e, 'Não foi possível importar.'));
      },
    });
  }
}

function cents(value: string): number {
  return Math.round(Number(value) * 100);
}
