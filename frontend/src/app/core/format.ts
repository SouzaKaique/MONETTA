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

/** Aceita "1.234,56", "1234,56" e "1234.56"; retorna string decimal ou null se inválido. */
export function parseMoney(text: string | null | undefined): string | null {
  const raw = (text ?? '').trim().replace(/^R\$\s*/, '');
  if (!raw) return null;
  const normalized = raw.includes(',') ? raw.replace(/\./g, '').replace(',', '.') : raw;
  if (!/^-?\d+(\.\d{1,2})?$/.test(normalized)) return null;
  return normalized;
}

/** Valor da API para o campo de edição: "1234.50" vira "1234,50". */
export function moneyToInput(value: string | null | undefined): string {
  return value ? value.replace('.', ',') : '';
}

/** Data ISO para exibição, sem conversão de fuso: "2026-03-05" vira "05/03/2026". */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const [year, month, day] = iso.slice(0, 10).split('-');
  return `${day}/${month}/${year}`;
}

export function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

export const PAYMENT_METHODS = [
  { value: 'pix', label: 'Pix' },
  { value: 'debit', label: 'Débito' },
  { value: 'cash', label: 'Dinheiro' },
  { value: 'boleto', label: 'Boleto' },
  { value: 'transfer', label: 'Transferência' },
  { value: 'other', label: 'Outro' },
];

export const FREQUENCIES = [
  { value: 'monthly', label: 'Mensal' },
  { value: 'biweekly', label: 'Quinzenal' },
  { value: 'weekly', label: 'Semanal' },
  { value: 'yearly', label: 'Anual' },
];

export function frequencyLabel(value: string): string {
  return FREQUENCIES.find((f) => f.value === value)?.label ?? value;
}
