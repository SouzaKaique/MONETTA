export interface NavItem {
  path: string;
  label: string;
  icon: string;
}

export const NAV_ITEMS: NavItem[] = [
  { path: '/', label: 'Dashboard', icon: 'bi-grid-1x2' },
  { path: '/receitas', label: 'Receitas', icon: 'bi-arrow-down-left-circle' },
  { path: '/despesas', label: 'Despesas', icon: 'bi-arrow-up-right-circle' },
  { path: '/cartoes', label: 'Cartões', icon: 'bi-credit-card' },
  { path: '/dividas', label: 'Dívidas', icon: 'bi-journal-check' },
  { path: '/planejamento', label: 'Planejamento', icon: 'bi-pie-chart' },
  { path: '/calendario', label: 'Calendário', icon: 'bi-calendar3' },
  { path: '/wishlist', label: 'Wishlist', icon: 'bi-bookmark-star' },
  { path: '/relatorios', label: 'Relatórios', icon: 'bi-bar-chart-line' },
  { path: '/configuracoes', label: 'Configurações', icon: 'bi-sliders' },
];

/** Itens fixos da barra inferior no celular; o restante fica em "Mais". */
const MOBILE_PATHS = ['/', '/despesas', '/cartoes', '/calendario'];
export const MOBILE_ITEMS = NAV_ITEMS.filter((i) => MOBILE_PATHS.includes(i.path));
export const MORE_ITEMS = NAV_ITEMS.filter((i) => !MOBILE_PATHS.includes(i.path));
