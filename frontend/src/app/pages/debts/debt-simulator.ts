import { Component, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import { FinanceService } from '../../core/finance.service';
import { formatMoney, formatMonth, parseMoney } from '../../core/format';
import { apiMessage } from '../../core/http';
import { DebtSimulation, DebtStrategy } from '../../core/models';
import { SimulationChart } from './simulation-chart';

@Component({
  selector: 'app-debt-simulator',
  imports: [ReactiveFormsModule, SimulationChart],
  template: `
    <div class="section-head">
      <h2 class="card-title-m">Simulador de quitação</h2>
    </div>
    <p class="subtle">Compare valores mensais. Segue a ordem de quitação escolhida acima.</p>

    <form class="inputs" [formGroup]="form" (ngSubmit)="run()" novalidate>
      <div>
        <label class="form-label" for="sim-a">Cenário 1</label>
        <input id="sim-a" class="form-control money" formControlName="first" inputmode="decimal" autocomplete="off" />
      </div>
      <div>
        <label class="form-label" for="sim-b">Cenário 2</label>
        <input id="sim-b" class="form-control money" formControlName="second" inputmode="decimal" autocomplete="off" />
      </div>
      <div>
        <label class="form-label" for="sim-c">Cenário 3</label>
        <input id="sim-c" class="form-control money" formControlName="third" inputmode="decimal" autocomplete="off" />
      </div>
      <div>
        <label class="form-label" for="sim-extra">Extra no 1º mês</label>
        <input id="sim-extra" class="form-control money" formControlName="extra" inputmode="decimal"
               placeholder="0,00" autocomplete="off" />
      </div>
      <button type="submit" class="btn btn-quiet">Simular</button>
    </form>

    @if (error()) { <p class="field-error" role="alert">{{ error() }}</p> }

    @if (result(); as r) {
      @if (r.capacity !== null) {
        <p class="subtle mt-3 mb-0">
          Depois das despesas e do mínimo de segurança, sobram {{ money(r.capacity) }} neste mês.
        </p>
      }
      <div class="scenarios">
        @for (s of r.scenarios; track $index) {
          <article class="scenario">
            <h3 class="money">{{ money(s.monthly) }} <small>por mês</small></h3>
            @if (s.feasible) {
              <p class="months">{{ s.months }} {{ s.months === 1 ? 'mês' : 'meses' }}</p>
              <dl>
                <div><dt>Quitação</dt><dd>{{ s.finish_month ? label(s.finish_month) : '—' }}</dd></div>
                <div><dt>Juros estimados</dt><dd class="money">{{ money(s.total_interest) }}</dd></div>
                <div><dt>Total pago</dt><dd class="money">{{ money(s.total_paid) }}</dd></div>
                @if ($index > 0 && s.months_saved !== null) {
                  <div>
                    <dt>Em relação ao 1º</dt>
                    <dd>{{ savedText(s.months_saved) }}</dd>
                  </div>
                }
              </dl>
            } @else {
              <p class="notice notice-warning mb-0">Este valor não cobre os juros: a dívida não termina.</p>
            }
            @if (s.above_capacity) {
              <p class="notice notice-warning mt-2 mb-0">
                Não recomendado: passa do que sobra e pode prejudicar despesas essenciais.
              </p>
            }
          </article>
        }
      </div>
      @if (hasChart()) {
        <app-simulation-chart class="d-block mt-3" [scenarios]="r.scenarios" />
      }
      <p class="subtle mt-2 mb-0">
        Estimativa com primeiro pagamento no mês que vem e juros mensais sobre o saldo.
      </p>
    }
  `,
  styles: `
    .inputs {
      align-items: end;
      display: grid;
      gap: 0.5rem;
      grid-template-columns: repeat(4, minmax(0, 1fr)) auto;
    }
    .scenarios {
      display: grid;
      gap: 0.5rem;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      margin-top: 0.75rem;
    }
    .scenario { background: var(--bg); border-radius: var(--radius-sm); padding: 0.9rem; }
    h3 { font-size: 1rem; font-weight: 600; margin: 0; }
    h3 small { color: var(--ink-3); font-size: 0.75rem; font-weight: 400; }
    .months { font-family: var(--font-display); font-size: 1.6rem; margin: 0.25rem 0 0.5rem; }
    dl { display: grid; gap: 0.2rem; margin: 0; }
    dl div { display: flex; font-size: 0.8125rem; justify-content: space-between; gap: 0.5rem; }
    dt { color: var(--ink-3); font-weight: 400; }
    dd { margin: 0; text-align: right; }
    dd::first-letter { text-transform: uppercase; }
    .notice { font-size: 0.8125rem; padding: 0.5rem 0.65rem; }
    @media (max-width: 767.98px) {
      .inputs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .inputs .btn { grid-column: 1 / -1; }
    }
  `,
})
export class DebtSimulator {
  private readonly finance = inject(FinanceService);
  private request?: Subscription;

  readonly strategy = input.required<DebtStrategy>();

  protected readonly result = signal<DebtSimulation | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly money = formatMoney;
  protected readonly label = formatMonth;
  protected readonly hasChart = computed(() =>
    (this.result()?.scenarios ?? []).some((s) => s.feasible && s.months),
  );

  protected readonly form = new FormGroup({
    first: new FormControl('300,00', { nonNullable: true }),
    second: new FormControl('500,00', { nonNullable: true }),
    third: new FormControl('750,00', { nonNullable: true }),
    extra: new FormControl('', { nonNullable: true }),
  });

  constructor() {
    // Atualiza sozinho quando um pagamento é registrado ou a ordem muda.
    effect(() => {
      this.finance.revision();
      this.strategy();
      untracked(() => this.run());
    });
  }

  protected savedText(months: number): string {
    if (months === 0) return 'Mesmo prazo';
    const count = Math.abs(months);
    const unit = count === 1 ? 'mês' : 'meses';
    return months > 0 ? `${count} ${unit} a menos` : `${count} ${unit} a mais`;
  }

  protected run(): void {
    this.error.set(null);
    const value = this.form.getRawValue();
    const amounts = [value.first, value.second, value.third]
      .filter((text) => text.trim())
      .map((text) => parseMoney(text));
    const extra = value.extra.trim() ? parseMoney(value.extra) : '0';
    if (!amounts.length || amounts.some((a) => !a || Number(a) <= 0) || extra === null) {
      this.error.set('Informe valores válidos, como 500,00.');
      return;
    }
    this.request?.unsubscribe();
    this.request = this.finance.simulateDebts({ amounts, extra, strategy: this.strategy() }).subscribe({
      next: (r) => this.result.set(r),
      error: (e) => this.error.set(apiMessage(e, 'Não foi possível simular.')),
    });
  }
}
