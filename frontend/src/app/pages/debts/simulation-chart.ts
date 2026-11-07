import {
  AfterViewInit, Component, ElementRef, OnDestroy, computed, effect, inject, input, signal, viewChild,
} from '@angular/core';
import {
  CategoryScale, Chart, LineController, LineElement, LinearScale, PointElement, Tooltip,
} from 'chart.js';
import { formatMoney, formatMonth, formatMonthShort } from '../../core/format';
import { DebtScenario } from '../../core/models';
import { ThemeService } from '../../core/theme.service';

Chart.register(CategoryScale, LineController, LineElement, LinearScale, PointElement, Tooltip);

const SERIES = ['--series-1', '--series-2', '--series-3'];

/** Evolução do saldo devedor de cada cenário, em um único eixo. */
@Component({
  selector: 'app-simulation-chart',
  template: `
    <div class="legend" aria-hidden="true">
      @for (s of drawable(); track s.monthly; let i = $index) {
        <span><i class="key" [style.background]="'var(' + series[i] + ')'"></i>{{ money(s.monthly) }} por mês</span>
      }
    </div>
    <div class="plot"><canvas #canvas role="img" aria-label="Evolução do saldo devedor; o resumo de cada cenário está acima."></canvas></div>
  `,
  styles: `
    .legend { color: var(--ink-2); display: flex; flex-wrap: wrap; font-size: 0.8125rem; gap: 0.25rem 1rem; margin-bottom: 0.5rem; }
    .key { border-radius: 2px; display: inline-block; height: 3px; margin-right: 0.4rem; vertical-align: middle; width: 14px; }
    .plot { height: 240px; position: relative; }
  `,
})
export class SimulationChart implements AfterViewInit, OnDestroy {
  readonly scenarios = input.required<DebtScenario[]>();

  private readonly theme = inject(ThemeService);
  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');
  private readonly ready = signal(false);
  private chart?: Chart;

  protected readonly series = SERIES;
  protected readonly money = formatMoney;
  protected readonly drawable = computed(() => this.scenarios().filter((s) => s.feasible));

  constructor() {
    effect(() => {
      const rows = this.drawable();
      this.theme.resolved();
      if (this.ready()) this.draw(rows);
    });
  }

  ngAfterViewInit(): void {
    this.ready.set(true);
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
  }

  private draw(rows: DebtScenario[]): void {
    const css = getComputedStyle(document.documentElement);
    const token = (name: string) => css.getPropertyValue(name).trim();
    const compact = new Intl.NumberFormat('pt-BR', { notation: 'compact' });
    const longest = rows.reduce<DebtScenario['timeline']>(
      (best, s) => (s.timeline.length > best.length ? s.timeline : best), [],
    );

    this.chart?.destroy();
    this.chart = new Chart(this.canvas().nativeElement, {
      type: 'line',
      data: {
        labels: longest.map((p) => formatMonthShort(p.month)),
        datasets: rows.map((s, i) => ({
          label: `${formatMoney(s.monthly)} por mês`,
          data: s.timeline.map((p) => Number(p.balance)),
          borderColor: token(SERIES[i]),
          backgroundColor: token(SERIES[i]),
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0,
        })),
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
              title: (items) => formatMonth(longest[items[0].dataIndex].month),
              label: (item) => ` ${item.dataset.label}: ${formatMoney(item.parsed.y)}`,
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            border: { color: token('--border') },
            ticks: { color: token('--ink-3'), maxTicksLimit: 8, maxRotation: 0 },
          },
          y: {
            beginAtZero: true,
            grid: { color: token('--border') },
            border: { display: false },
            ticks: { color: token('--ink-3'), maxTicksLimit: 5, callback: (v) => compact.format(Number(v)) },
          },
        },
      },
    });
  }
}
