import {
  AfterViewInit, Component, ElementRef, OnDestroy, computed, effect, inject, input, signal, viewChild,
} from '@angular/core';
import {
  BarController, BarElement, CategoryScale, Chart, LinearScale, Tooltip,
} from 'chart.js';
import { formatMoney, formatMonth, formatMonthShort } from '../../core/format';
import { HistoryPoint } from '../../core/models';
import { ThemeService } from '../../core/theme.service';

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip);

/** Colunas agrupadas: receitas confirmadas e despesas por competência dos últimos meses. */
@Component({
  selector: 'app-history-chart',
  template: `
    <div class="legend" aria-hidden="true">
      <span><i class="swatch income"></i>Receitas</span>
      <span><i class="swatch expenses"></i>Despesas</span>
    </div>
    <div class="plot"><canvas #canvas role="img" [attr.aria-label]="summary()"></canvas></div>
    <table class="visually-hidden">
      <caption>Receitas e despesas por mês</caption>
      <thead><tr><th>Mês</th><th>Receitas</th><th>Despesas</th></tr></thead>
      <tbody>
        @for (row of data(); track row.month) {
          <tr><td>{{ long(row.month) }}</td><td>{{ money(row.income) }}</td><td>{{ money(row.expenses) }}</td></tr>
        }
      </tbody>
    </table>
  `,
  styles: `
    .legend { color: var(--ink-2); display: flex; font-size: 0.8125rem; gap: 1rem; margin-bottom: 0.75rem; }
    .swatch { border-radius: 3px; display: inline-block; height: 10px; margin-right: 0.4rem; width: 10px; }
    .income { background: var(--series-1); }
    .expenses { background: var(--series-2); }
    .plot { height: 240px; position: relative; }
  `,
})
export class HistoryChart implements AfterViewInit, OnDestroy {
  readonly data = input.required<HistoryPoint[]>();

  private readonly theme = inject(ThemeService);
  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');
  private readonly ready = signal(false);
  private chart?: Chart;

  protected readonly summary = computed(
    () => `Receitas e despesas de ${this.data().length} meses; os valores estão na tabela a seguir.`,
  );
  protected readonly money = formatMoney;
  protected readonly long = formatMonth;

  constructor() {
    effect(() => {
      const rows = this.data();
      this.theme.resolved(); // redesenha ao trocar de tema
      if (this.ready()) this.draw(rows);
    });
  }

  ngAfterViewInit(): void {
    this.ready.set(true);
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
  }

  private draw(rows: HistoryPoint[]): void {
    const css = getComputedStyle(document.documentElement);
    const token = (name: string) => css.getPropertyValue(name).trim();
    const compact = new Intl.NumberFormat('pt-BR', { notation: 'compact' });
    const bar = { borderRadius: 4, borderSkipped: 'bottom' as const, maxBarThickness: 24 };

    this.chart?.destroy();
    this.chart = new Chart(this.canvas().nativeElement, {
      type: 'bar',
      data: {
        labels: rows.map((r) => formatMonthShort(r.month)),
        datasets: [
          { label: 'Receitas', data: rows.map((r) => Number(r.income)), backgroundColor: token('--series-1'), ...bar },
          { label: 'Despesas', data: rows.map((r) => Number(r.expenses)), backgroundColor: token('--series-2'), ...bar },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 250 },
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => formatMonth(rows[items[0].dataIndex].month),
              label: (item) => ` ${item.dataset.label}: ${formatMoney(item.parsed.y)}`,
            },
          },
        },
        scales: {
          x: { grid: { display: false }, border: { color: token('--border') }, ticks: { color: token('--ink-3') } },
          y: {
            beginAtZero: true,
            suggestedMax: 1000,
            grid: { color: token('--border') },
            border: { display: false },
            ticks: { color: token('--ink-3'), maxTicksLimit: 5, callback: (v) => compact.format(Number(v)) },
          },
        },
      },
    });
  }
}
