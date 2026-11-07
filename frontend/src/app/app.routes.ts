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
      {
        path: 'cartoes',
        loadComponent: () => import('./pages/cards/cards').then((m) => m.CardsPage),
      },
      {
        path: 'cartoes/:id',
        loadComponent: () => import('./pages/cards/card-detail').then((m) => m.CardDetailPage),
      },
      {
        path: 'dividas',
        loadComponent: () => import('./pages/debts/debts').then((m) => m.DebtsPage),
      },
      {
        path: 'planejamento',
        loadComponent: () => import('./pages/planning/planning').then((m) => m.PlanningPage),
      },
      {
        path: 'calendario',
        loadComponent: () => import('./pages/calendar/calendar').then((m) => m.CalendarPage),
      },
      {
        path: 'recuperacao',
        loadComponent: () => import('./pages/recovery/recovery').then((m) => m.RecoveryPage),
      },
      {
        path: 'notificacoes',
        loadComponent: () => import('./pages/notifications/notifications').then((m) => m.NotificationsPage),
      },
      { path: 'wishlist', ...upcoming('Wishlist', 6, 'Metas de compra e a análise "Posso comprar?".') },
      { path: 'relatorios', ...upcoming('Relatórios', 7, 'Gráficos por período e exportação em CSV.') },
    ],
  },
  { path: '**', redirectTo: '' },
];
