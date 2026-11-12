import { Component, OnInit, inject, input, output, signal, viewChild } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FinanceService } from '../../core/finance.service';
import { moneyToInput, parseMoney } from '../../core/format';
import { apiMessage } from '../../core/http';
import { CreditCard } from '../../core/models';
import { Dialog } from '../../shared/dialog';

export const CARD_COLORS = ['forest', 'graphite', 'wine', 'navy', 'ochre', 'plum'];

@Component({
  selector: 'app-card-form',
  imports: [ReactiveFormsModule, Dialog],
  template: `
    <app-dialog [heading]="card() ? 'Editar cartão' : 'Novo cartão'" (closed)="closed.emit()">
      <form [formGroup]="form" (ngSubmit)="save()" novalidate>
        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="cd-name">Nome</label>
            <input id="cd-name" class="form-control" formControlName="name" maxlength="80" />
          </div>
          <div>
            <label class="form-label" for="cd-bank">Instituição</label>
            <input id="cd-bank" class="form-control" formControlName="institution" maxlength="80" />
          </div>
        </div>
        <div class="mb-3">
          <label class="form-label" for="cd-limit">Limite total</label>
          <input id="cd-limit" class="form-control money" formControlName="credit_limit"
                 inputmode="decimal" placeholder="0,00" autocomplete="off" />
        </div>
        <div class="grid-2 mb-3">
          <div>
            <label class="form-label" for="cd-closing">Dia do fechamento</label>
            <input id="cd-closing" class="form-control" type="number" min="1" max="31" formControlName="closing_day" />
            <div class="subtle mt-1">Compras desse dia já vão para a fatura seguinte.</div>
          </div>
          <div>
            <label class="form-label" for="cd-due">Dia do vencimento</label>
            <input id="cd-due" class="form-control" type="number" min="1" max="31" formControlName="due_day" />
          </div>
        </div>
        @if (card()) {
          <p class="subtle">Novos dias valem para faturas que ainda não fecharam.</p>
        }
        <p class="form-label">Cor</p>
        <div class="swatches mb-3" role="radiogroup" aria-label="Cor do cartão">
          @for (c of colors; track c) {
            <button type="button" role="radio" class="swatch card-{{ c }}"
                    [class.selected]="form.controls.color.value === c"
                    [attr.aria-checked]="form.controls.color.value === c"
                    [attr.aria-label]="c" (click)="form.controls.color.setValue(c)"></button>
          }
        </div>
        @if (error()) { <p class="field-error mb-2" role="alert">{{ error() }}</p> }
        <button type="submit" class="btn btn-brand w-100" [disabled]="busy()">Salvar</button>
      </form>
    </app-dialog>
  `,
  styles: `
    .swatches { display: flex; gap: 0.5rem; }
    .swatch { border: 2px solid transparent; border-radius: 50%; height: 30px; width: 30px; }
    .swatch.selected { box-shadow: 0 0 0 2px var(--surface), 0 0 0 4px var(--accent); }
  `,
})
export class CardForm implements OnInit {
  private readonly finance = inject(FinanceService);

  readonly card = input<CreditCard | null>(null);
  readonly closed = output<void>();

  private readonly dialog = viewChild.required(Dialog);
  protected readonly colors = CARD_COLORS;
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly form = new FormGroup({
    name: new FormControl('', { nonNullable: true }),
    institution: new FormControl('', { nonNullable: true }),
    credit_limit: new FormControl('', { nonNullable: true }),
    closing_day: new FormControl<number | null>(null),
    due_day: new FormControl<number | null>(null),
    color: new FormControl('forest', { nonNullable: true }),
  });

  ngOnInit(): void {
    const card = this.card();
    if (card) {
      this.form.patchValue({
        name: card.name,
        institution: card.institution ?? '',
        credit_limit: moneyToInput(card.credit_limit),
        closing_day: card.closing_day,
        due_day: card.due_day,
        color: card.color,
      });
    }
  }

  protected save(): void {
    if (this.busy()) return;
    this.error.set(null);
    const value = this.form.getRawValue();
    const limit = parseMoney(value.credit_limit);
    if (!value.name.trim()) {
      this.error.set('Informe o nome do cartão.');
      return;
    }
    if (limit === null || Number(limit) < 0) {
      this.error.set('Informe um limite válido, como 5.000,00.');
      return;
    }
    if (!value.closing_day || !value.due_day) {
      this.error.set('Informe os dias de fechamento e vencimento.');
      return;
    }
    this.busy.set(true);
    this.finance.saveCard({
      ...value,
      name: value.name.trim(),
      institution: value.institution.trim() || null,
      credit_limit: limit,
    }, this.card()?.id).subscribe({
      next: () => this.dialog().close(),
      error: (e) => {
        this.error.set(apiMessage(e, 'Não foi possível salvar.'));
        this.busy.set(false);
      },
    });
  }
}
