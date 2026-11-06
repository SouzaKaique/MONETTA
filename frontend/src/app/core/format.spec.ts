import { formatMoney, formatMonth, initials, shiftMonth } from './format';

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
