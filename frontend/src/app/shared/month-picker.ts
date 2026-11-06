import { Component, computed, input, output } from '@angular/core';
import { formatMonth, shiftMonth } from '../core/format';

@Component({
  selector: 'app-month-picker',
  template: `
    <div class="picker" role="group" aria-label="Selecionar mês">
      <button type="button" class="btn btn-quiet" aria-label="Mês anterior" [disabled]="disabled()"
              (click)="monthChange.emit(step(-1))">
        <i class="bi bi-chevron-left" aria-hidden="true"></i>
      </button>
      <span class="label" aria-live="polite">{{ label() }}</span>
      <button type="button" class="btn btn-quiet" aria-label="Próximo mês" [disabled]="disabled()"
              (click)="monthChange.emit(step(1))">
        <i class="bi bi-chevron-right" aria-hidden="true"></i>
      </button>
    </div>
  `,
  styles: `
    .picker { align-items: center; display: flex; gap: 0.4rem; }
    .btn { padding: 0.3rem 0.6rem; }
    .label { font-weight: 500; min-width: 10.5rem; text-align: center; }
    .label::first-letter { text-transform: uppercase; }
    @media (max-width: 767.98px) { .picker { justify-content: space-between; width: 100%; } }
  `,
  host: { style: 'display: block' },
})
export class MonthPicker {
  readonly month = input.required<string>();
  readonly disabled = input(false);
  readonly monthChange = output<string>();
  protected readonly label = computed(() => formatMonth(this.month()));

  protected step(delta: number): string {
    return shiftMonth(this.month(), delta);
  }
}
