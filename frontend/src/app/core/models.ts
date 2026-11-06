export type ThemePreference = 'system' | 'light' | 'dark';

export interface User {
  id: string;
  email: string;
  account_name: string;
  avatar_url: string | null;
  has_password: boolean;
  providers: string[];
  theme: ThemePreference;
  safety_minimum: string;
  created_at: string;
}

export interface Providers {
  google: boolean;
  apple: boolean;
}

/** Valores monetários chegam como string decimal; `null` significa "ainda não disponível". */
export type Money = string | null;

export type Kind = 'income' | 'expense';
export type Frequency = 'weekly' | 'biweekly' | 'monthly' | 'yearly';

export interface DashboardSummary {
  balance: Money;
  income_expected: string;
  income_received: string;
  salary_received: string;
  salary_expected: string;
  extra_income: string;
  expenses_total: string;
  expenses_paid: string;
  expenses_pending: string;
  expenses_fixed: string;
  expenses_variable: string;
  income_commitment_pct: number | null;
  free_money: string;
  safety_minimum: string;
  overdue_expenses: string;
  available_to_spend: Money;
  projected_balance: Money;
  card_commitment: Money;
  debt_payments: Money;
  reserves: Money;
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
  has_accounts: boolean;
  has_salary: boolean;
  has_data: boolean;
  summary: DashboardSummary;
  history: HistoryPoint[];
  by_category: { category: string; total: string }[];
  alerts: { level: 'warning' | 'critical'; message: string }[];
}

export interface Account {
  id: string;
  name: string;
  type: 'checking' | 'savings' | 'cash';
  opening_balance: string;
  opening_date: string;
  balance: string;
  real_balance: Money;
  real_balance_on: string | null;
  difference: Money;
  active: boolean;
}

export interface Category {
  id: string;
  name: string;
  kind: Kind;
  icon: string;
  is_default: boolean;
}

export interface Transaction {
  id: string;
  kind: Kind;
  status: 'pending' | 'confirmed';
  description: string;
  amount: string;
  competence_date: string;
  paid_on: string | null;
  account_id: string | null;
  account_name: string | null;
  category_id: string | null;
  category_name: string | null;
  payment_method: string | null;
  notes: string | null;
  is_salary: boolean;
  is_fixed: boolean;
  recurrence_id: string | null;
}

export interface TransactionPage {
  items: Transaction[];
  count: number;
  total: string;
  page: number;
  per_page: number;
}

export interface Recurrence {
  id: string;
  kind: Kind;
  name: string;
  is_salary: boolean;
  amount: string;
  frequency: Frequency;
  day_of_month: number;
  start_date: string;
  end_date: string | null;
  active: boolean;
  next_date: string | null;
  category_id: string | null;
  category_name: string | null;
  account_id: string | null;
  payment_method: string | null;
  notes: string | null;
  amount_history: { amount: string; effective_from: string }[];
}

export interface Transfer {
  id: string;
  amount: string;
  date: string;
  from_account: string;
  to_account: string;
  notes: string | null;
}
