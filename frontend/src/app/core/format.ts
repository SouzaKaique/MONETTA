const brl = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const monthLong = new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric', timeZone: 'UTC' });
const monthShort = new Intl.DateTimeFormat('pt-BR', { month: 'short', timeZone: 'UTC' });

/** Apenas exibição. Nenhuma conta financeira acontece no frontend. */
export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  // Troca o espaço rígido do Intl por um comum para facilitar cópia e leitura.
  return brl.format(Number(value)).replace(/ /g, ' ');
}

function monthDate(month: string): Date {
  const [year, m] = month.split('-').map(Number);
  return new Date(Date.UTC(year, m - 1, 1));
}

export function formatMonth(month: string): string {
  return monthLong.format(monthDate(month));
}

export function formatMonthShort(month: string): string {
  return monthShort.format(monthDate(month)).replace('.', '');
}

export function shiftMonth(month: string, delta: number): string {
  const [year, m] = month.split('-').map(Number);
  const date = new Date(Date.UTC(year, m - 1 + delta, 1));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : parts[0].slice(0, 2);
  return letters.toUpperCase();
}
