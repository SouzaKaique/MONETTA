import { formatDate, formatMoney, formatMonth, initials, moneyToInput, parseMoney, shiftMonth } from './format';

describe('format', () => {
  it('formata dinheiro em reais e mostra traço quando não há valor', () => {
    expect(formatMoney('1234.50')).toBe('R$ 1.234,50');
    expect(formatMoney(null)).toBe('—');
  });

  it('navega entre meses atravessando o ano', () => {
    expect(shiftMonth('2026-01', -1)).toBe('2025-12');
    expect(shiftMonth('2026-12', 1)).toBe('2027-01');
  });

  it('escreve o mês por extenso', () => {
    expect(formatMonth('2026-11')).toBe('novembro de 2026');
  });

  it('gera iniciais do nome da conta', () => {
    expect(initials('Ana Souza Lima')).toBe('AL');
    expect(initials('Kaique')).toBe('KA');
  });
});

describe('parseMoney', () => {
  it('entende o formato brasileiro e o formato decimal', () => {
    expect(parseMoney('1.234,56')).toBe('1234.56');
    expect(parseMoney('1234,5')).toBe('1234.5');
    expect(parseMoney('R$ 80,00')).toBe('80.00');
    expect(parseMoney('99.90')).toBe('99.90');
    expect(parseMoney('250')).toBe('250');
  });

  it('recusa texto inválido e mais de duas casas', () => {
    expect(parseMoney('')).toBeNull();
    expect(parseMoney('abc')).toBeNull();
    expect(parseMoney('1,234')).toBeNull();
    expect(parseMoney('1.2.3')).toBeNull();
  });
});

describe('moneyToInput e formatDate', () => {
  it('converte para exibição', () => {
    expect(moneyToInput('1234.50')).toBe('1234,50');
    expect(formatDate('2026-03-05')).toBe('05/03/2026');
    expect(formatDate(null)).toBe('—');
  });
});
