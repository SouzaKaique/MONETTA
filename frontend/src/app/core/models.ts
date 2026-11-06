export type ThemePreference = 'system' | 'light' | 'dark';

export interface User {
  id: string;
  email: string;
  account_name: string;
  avatar_url: string | null;
  has_password: boolean;
  providers: string[];
  theme: ThemePreference;
  created_at: string;
}

export interface Providers {
  google: boolean;
  apple: boolean;
}

/** Valores monetários chegam como string decimal; `null` significa "ainda não disponível". */
export type Money = string | null;

export interface DashboardSummary {
  balance: Money;
  salary_received: string;
  salary_expected: string;
  extra_income: string;
  expenses_total: string;
  expenses_paid: string;
  expenses_pending: string;
  income_commitment_pct: number | null;
  safety_minimum: string;
  available_to_spend: Money;
  projected_balance: Money;
  open_invoices: Money;
  pending_debts: Money;
  saved_total: Money;
}

export interface HistoryPoint {
  month: string;
  income: string;
  expenses: string;
}

export interface Dashboard {
  month: string;
  is_current_month: boolean;
  has_data: boolean;
  summary: DashboardSummary;
  history: HistoryPoint[];
  by_category: { category: string; total: string }[];
  alerts: { level: 'warning' | 'critical'; message: string }[];
}
