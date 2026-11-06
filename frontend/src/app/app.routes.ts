import { Routes } from '@angular/router';
import { authGuard } from './core/http';

/** Áreas que ainda não existem: a rota explica o que vem e em qual etapa. */
const upcoming = (title: string, stage: number, description: string) => ({
  loadComponent: () => import('./pages/upcoming/upcoming').then((m) => m.Upcoming),
  data: { title, stage, description },
});

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./pages/auth/auth').then((m) => m.AuthPage),
    data: { mode: 'login' },
  },
  {
    path: 'cadastro',
    loadComponent: () => import('./pages/auth/auth').then((m) => m.AuthPage),
    data: { mode: 'register' },
  },
  {
    path: '',
    canActivate: [authGuard],
    loadComponent: () => import('./layout/shell').then((m) => m.Shell),
    children: [
      {
        path: '',
        pathMatch: 'full',
        loadComponent: () => import('./pages/dashboard/dashboard').then((m) => m.DashboardPage),
      },
      {
        path: 'perfil',
        loadComponent: () => import('./pages/profile/profile').then((m) => m.ProfilePage),
      },
      {
        path: 'receitas',
        loadComponent: () => import('./pages/income/income').then((m) => m.IncomePage),
      },
      {
        path: 'despesas',
        loadComponent: () => import('./pages/expenses/expenses').then((m) => m.ExpensesPage),
      },
      {
        path: 'configuracoes',
        loadComponent: () => import('./pages/settings/settings').then((m) => m.SettingsPage),
      },
      { path: 'cartoes', ...upcoming('Cartões de crédito', 3, 'Limites, faturas, compras parceladas e pagamentos.') },
      { path: 'dividas', ...upcoming('Dívidas', 4, 'Histórico de pagamentos, estratégias de quitação e simulador.') },
      { path: 'planejamento', ...upcoming('Planejamento', 5, 'Orçamento mensal, simulador até o próximo salário e Modo Recuperação.') },
      { path: 'calendario', ...upcoming('Calendário', 5, 'Tudo o que entra e sai, dia a dia.') },
      { path: 'wishlist', ...upcoming('Wishlist', 6, 'Metas de compra e a análise "Posso comprar?".') },
      { path: 'relatorios', ...upcoming('Relatórios', 7, 'Gráficos por período e exportação em CSV.') },
    ],
  },
  { path: '**', redirectTo: '' },
];
