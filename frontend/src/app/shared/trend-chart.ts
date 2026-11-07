import {
  AfterViewInit, Component, ElementRef, OnDestroy, computed, effect, inject, input, signal, viewChild,
} from '@angular/core';
import {
  BarController, BarElement, CategoryScale, Chart, LineController, LineElement, LinearScale,
  PointElement, Tooltip,
} from 'chart.js';
import { formatMoney } from '../core/format';
import { ThemeService } from '../core/theme.service';

Chart.register(
  BarController, BarElement, CategoryScale, LineController, LineElement, LinearScale,
  PointElement, Tooltip,
);

export interface TrendSeries {
  label: string;
  values: (number | null)[];
  token: string; // variável de cor do tema, como --series-1
}

/** Gráfico de um eixo só, com legenda para duas séries ou mais e tabela para leitores de tela. */
@Component({
  selector: 'app-trend-chart',
  template: `
    @if (series().length > 1) {
      <div class="legend" aria-hidden="true">
        @for (s of series(); track s.label) {
          <span><i class="key" [style.background]="'var(' + s.token + ')'"></i>{{ s.label }}</span>
        }
      </div>
    }
    <div class="plot" [style.height.px]="height()">
      <canvas #canvas role="img" [attr.aria-label]="title() + '; os valores estão na tabela a seguir.'"></canvas>
    </div>
    <table class="visually-hidden">
      <caption>{{ title() }}</caption>
      <thead>
        <tr><th>Período</th>@for (s of series(); track s.label) { <th>{{ s.label }}</th> }</tr>
      </thead>
      <tbody>
        @for (label of labels(); track $index; let i = $index) {
          <tr>
            <td>{{ label }}</td>
            @for (s of series(); track s.label) { <td>{{ text(s.values[i]) }}</td> }
          </tr>
        }
      </tbody>
    </table>
  `,
  styles: `
    .legend { color: var(--ink-2); display: flex; flex-wrap: wrap; font-size: 0.8125rem; gap: 0.25rem 1rem; margin-bottom: 0.5rem; }
    .key { border-radius: 3px; display: inline-block; height: 10px; margin-right: 0.4rem; width: 10px; }
    .plot { position: relative; }
  `,
})
export class TrendChart implements AfterViewInit, OnDestroy {
  readonly title = input.required<string>();
  readonly labels = input.required<string[]>();
  readonly series = input.required<TrendSeries[]>();
  readonly kind = input<'line' | 'bar'>('line');
  readonly format = input<'money' | 'pct'>('money');
  readonly height = input(200);

  private readonly theme = inject(ThemeService);
  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');
  private readonly ready = signal(false);
  private readonly payload = computed(() => ({
    labels: this.labels(), series: this.series(), kind: this.kind(), format: this.format(),
  }));
  private chart?: Chart;

  constructor() {
    effect(() => {
      const payload = this.payload();
      this.theme.resolved();
      if (this.ready()) this.draw(payload);
    });
  }

  ngAfterViewInit(): void {
    this.ready.set(true);
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
  }

  protected text(value: number | null | undefined): string {
    if (value === null || value === undefined) return '—';
    return this.format() === 'pct' ? `${value}%` : formatMoney(value);
  }

  private draw({ labels, series, kind, format }: ReturnType<typeof this.payload>): void {
    const css = getComputedStyle(document.documentElement);
    const token = (name: string) => css.getPropertyValue(name).trim();
    const compact = new Intl.NumberFormat('pt-BR', { notation: 'compact' });
    const marks = kind === 'bar'
      ? { borderRadius: 4, borderSkipped: 'bottom' as const, maxBarThickness: 24 }
      : { borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0, spanGaps: false };

    this.chart?.destroy();
    this.chart = new Chart(this.canvas().nativeElement, {
      type: kind,
      data: {
        labels,
        datasets: series.map((s) => ({
          label: s.label, data: s.values,
          backgroundColor: token(s.token), borderColor: token(s.token), ...marks,
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
            callbacks: { label: (item) => ` ${item.dataset.label}: ${this.text(item.parsed.y)}` },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            border: { color: token('--border') },
            ticks: { color: token('--ink-3'), maxRotation: 0, autoSkipPadding: 12 },
          },
          y: {
            beginAtZero: true,
            grid: { color: token('--border') },
            border: { display: false },
            ticks: {
              color: token('--ink-3'), maxTicksLimit: 5,
              callback: (v) => (format === 'pct' ? `${v}%` : compact.format(Number(v))),
            },
          },
        },
      },
    });
  }
}
