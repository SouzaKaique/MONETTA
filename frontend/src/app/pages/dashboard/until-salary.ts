import { Component, effect, inject, signal, untracked } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Subscription, debounceTime } from 'rxjs';
import { FinanceService } from '../../core/finance.service';
import { formatDate, formatMoney, parseMoney } from '../../core/format';
import { UntilSalary } from '../../core/models';

/** Destaque do dashboard: "Quanto posso gastar até o próximo salário?" */
@Component({
  selector: 'app-until-salary',
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <section class="card-m mt-3 until" aria-labelledby="until-title">
      <h2 id="until-title" class="card-title-m">Quanto posso gastar até o próximo salário?</h2>
      @if (data(); as d) {
        @if (!d.has_salary) {
          <p class="subtle mt-2 mb-0">
            <a routerLink="/receitas">Cadastre seu salário</a> para calcular este valor.
          </p>
        } @else {
          <div class="main-row">
            <div>
              <p class="value display money">{{ money(d.available) }}</p>
              <p class="subtle mb-0">
                {{ d.days_left }} {{ d.days_left === 1 ? 'dia' : 'dias' }} até {{ date(d.next_salary_date) }}
              </p>
            </div>
            <dl class="limits">
              <div><dt>Por dia</dt><dd class="money">{{ money(d.daily_limit) }}</dd></div>
              <div><dt>Por semana</dt><dd class="money">{{ money(d.weekly_limit) }}</dd></div>
              <div><dt>Compromissos</dt><dd class="money">{{ money(d.committed) }}</dd></div>
            </dl>
          </div>

          @if (hasShortfall(d)) {
            <p class="notice notice-critical mt-2 mb-0">
              Faltam {{ money(d.shortfall) }} para cobrir os compromissos até o salário.
            </p>
          }

          <div class="scenario">
            <label class="form-label" for="until-spend">E se eu gastar</label>
            <input id="until-spend" class="form-control money" [formControl]="spend"
                   inputmode="decimal" placeholder="0,00" autocomplete="off" />
            @if (invalid()) { <p class="field-error">Informe um valor como 150,00.</p> }
          </div>

          @if (d.commitments?.length) {
            <details class="mt-2">
              <summary class="subtle">Ver compromissos</summary>
              <ul class="rows mt-1">
                @for (c of d.commitments; track $index) {
                  <li class="row-item compact">
                    <div class="row-main">
                      <span>{{ c.label }}</span>
                      @if (c.date) { <span class="row-meta">{{ date(c.date) }}</span> }
                    </div>
                    <span class="row-amount money">{{ money(c.amount) }}</span>
                  </li>
                }
              </ul>
              @if (safety(d)) {
                <p class="subtle mb-0">Também fica guardado o mínimo de segurança de {{ money(d.safety_minimum) }}.</p>
              }
            </details>
          }
        }
      }
    </section>
  `,
  styles: `
    .main-row { align-items: flex-end; display: flex; flex-wrap: wrap; gap: 1rem 2rem; justify-content: space-between; margin-top: 0.5rem; }
    .value { font-size: clamp(1.9rem, 5vw, 2.5rem); line-height: 1.1; margin: 0 0 0.2rem; }
    .limits { display: flex; flex-wrap: wrap; gap: 0.5rem 1.75rem; margin: 0; }
    dt { color: var(--ink-3); font-size: 0.75rem; font-weight: 400; }
    dd { font-weight: 600; margin: 0; }
    .scenario { margin-top: 0.9rem; max-width: 220px; }
    .compact { padding: 0.4rem 0; }
    .notice { font-size: 0.8125rem; }
  `,
})
export class UntilSalaryCard {
  private readonly finance = inject(FinanceService);
  private request?: Subscription;

  protected readonly data = signal<UntilSalary | null>(null);
  protected readonly invalid = signal(false);
  protected readonly money = formatMoney;
  protected readonly date = formatDate;
  protected readonly spend = new FormControl('', { nonNullable: true });

  constructor() {
    effect(() => {
      this.finance.revision();
      untracked(() => this.load());
    });
    this.spend.valueChanges.pipe(debounceTime(300)).subscribe(() => this.load());
  }

  protected hasShortfall(d: UntilSalary): boolean {
    return Number(d.shortfall ?? 0) > 0;
  }

  protected safety(d: UntilSalary): boolean {
    return Number(d.safety_minimum ?? 0) > 0;
  }

  private load(): void {
    const text = this.spend.value.trim();
    const amount = text ? parseMoney(text) : undefined;
    this.invalid.set(amount === null || Number(amount ?? 0) < 0);
    if (this.invalid()) return;
    this.request?.unsubscribe();
    this.request = this.finance.untilSalary(amount ?? undefined).subscribe({
      next: (d) => this.data.set(d),
      error: () => this.data.set(null),
    });
  }
}
