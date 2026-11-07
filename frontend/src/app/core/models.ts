export type ThemePreference = 'system' | 'light' | 'dark';

export interface AlertPrefs {
  budget_pct: number;
  card_pct: number;
  commitment_pct: number;
  due_days: number;
  muted: string[];
}

export interface User {
  id: string;
  email: string;
  account_name: string;
  avatar_url: string | null;
  has_password: boolean;
  providers: string[];
  theme: ThemePreference;
  safety_minimum: string;
  debt_strategy: DebtStrategy;
  planned_reserve: string;
  alert_prefs: AlertPrefs;
  created_at: string;
}

export interface Providers {
  google: boolean;
  apple: boolean;
}

/** Valores monetários chegam como string decimal; `null` significa "ainda não disponível". */
export type Money = string | null;

export type Kind = 'income' | 'expense';
export type DebtStrategy = 'snowball' | 'avalanche' | 'due_date' | 'priority' | 'custom';
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
  card_commitment: string;
  open_invoices: string;
  overdue_invoices: string;
  debt_payments: string;
  debt_due: string;
  pending_debts: string;
  reserves: Money;
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
  recovery_active: boolean;
  summary: DashboardSummary;
  history: HistoryPoint[];
  by_category: { category: string; total: string }[];
  alerts: { level: 'info' | 'warning' | 'critical'; message: string; link?: string | null }[];
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
  is_essential: boolean;
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

export interface CreditCard {
  id: string;
  name: string;
  institution: string | null;
  credit_limit: string;
  closing_day: number;
  due_day: number;
  color: string;
  active: boolean;
  used: string;
  available: string;
  usage_pct: number | null;
  current_invoice: string;
  future_invoices: string;
  remaining_installments: number;
  next_due_date: string | null;
  next_due_amount: string;
}

export type InvoiceStatus = 'future' | 'open' | 'closed' | 'partial' | 'paid' | 'overdue';

export interface Invoice {
  id: string;
  card_id: string;
  card_name: string;
  month: string;
  closing_date: string;
  due_date: string;
  total: string;
  paid: string;
  remaining: string;
  status: InvoiceStatus;
}

export interface Installment {
  id: string;
  purchase_id: string;
  description: string;
  number: number;
  count: number;
  amount: string;
  purchase_date: string;
  category_name: string | null;
  card_name: string;
  due_date: string | null;
}

export interface InvoiceDetail extends Invoice {
  installments: Installment[];
  payments: { id: string; amount: string; paid_on: string; account_name: string }[];
}

export interface CardDetail extends CreditCard {
  invoices: Invoice[];
  spending: { month: string; total: string }[];
}

export interface Purchase {
  id: string;
  card_id: string;
  description: string;
  total_amount: string;
  purchase_date: string;
  installment_count: number;
  category_name: string | null;
  first_due_date: string | null;
  last_due_date: string | null;
}

export interface DebtPayment {
  id: string;
  amount: string;
  paid_on: string;
  description: string | null;
  notes: string | null;
  account_name: string | null;
}

export interface Debt {
  id: string;
  name: string;
  creditor: string;
  original_amount: string;
  opening_balance: string;
  balance: string;
  total_paid: string;
  paid_pct: number;
  status: 'pending' | 'in_payment' | 'paid';
  start_date: string;
  due_date: string | null;
  agreed_amount: Money;
  frequency: 'none' | 'weekly' | 'biweekly' | 'monthly';
  interest_rate: Money;
  priority: number;
  notes: string | null;
  payments: DebtPayment[];
}

export interface DebtList {
  strategy: DebtStrategy;
  items: Debt[];
  summary: {
    original: string;
    paid: string;
    balance: string;
    paid_pct: number;
    monthly_commitment: string;
    next_debt: string | null;
  };
}

export interface DebtScenario {
  monthly: string;
  above_capacity: boolean;
  feasible: boolean;
  months: number | null;
  finish_month: string | null;
  total_interest: Money;
  total_paid: Money;
  timeline: { month: string; balance: string }[];
  payoff: { name: string; month: string; months: number }[];
  months_saved: number | null;
  interest_saved: Money;
}

export interface DebtSimulation {
  strategy: DebtStrategy;
  capacity: Money;
  scenarios: DebtScenario[];
}

export interface UntilSalary {
  has_salary: boolean;
  next_salary_date?: string;
  days_left?: number;
  balance?: string;
  committed?: string;
  safety_minimum?: string;
  commitments?: { kind: string; label: string; date: string | null; amount: string }[];
  scenario_spend?: string;
  available?: string;
  shortfall?: string;
  daily_limit?: string;
  weekly_limit?: string;
}

export interface BudgetRow {
  category_id: string | null;
  name: string;
  icon: string;
  is_essential: boolean;
  limit: Money;
  spent: string;
  remaining: Money;
  pct: number | null;
}

export interface Planning {
  month: string;
  is_current_month: boolean;
  income_expected: string;
  income_received: string;
  expenses_paid: string;
  expenses_pending: string;
  card_commitment: string;
  future_commitments: string;
  reserved: string;
  projected_balance: Money;
  available: Money;
  commitment_pct: number | null;
  distribution: { key: string; label: string; amount: Money }[];
  budgets: BudgetRow[];
}

export interface CalendarEvent {
  id: string;
  type: string;
  date: string;
  title: string;
  amount: Money;
  status: 'pending' | 'done';
  transaction_id?: string;
  link: string;
}

export interface RecoveryConfig {
  active: boolean;
  monthly_amount: string;
  strategy: DebtStrategy;
  priority_debt_ids: string[];
  non_essential_limit: Money;
  reserve_minimum: string;
  spending_goal_pct: number | null;
  target_date: string | null;
  started_on: string;
  ended_on: string | null;
}

export interface RecoveryStatus {
  initial_debt: string;
  current_debt: string;
  paid: string;
  reduction_pct: number;
  available_for_payments: Money;
  paid_this_month: string;
  next_debt: string | null;
  forecast: { feasible: boolean; months: number | null; finish_month: string | null; total_interest: Money };
  on_target: boolean | null;
  evolution: { month: string; balance: string }[];
  non_essential: { spent: string; limit: Money; baseline: Money; goal_amount: Money };
  recommendations: string[];
}

export interface Recovery {
  configured: boolean;
  active: boolean;
  config?: RecoveryConfig;
  status?: RecoveryStatus;
}

export interface RecoveryImpact {
  amount: string;
  months_before: number | null;
  months_after: number | null;
  delay_months: number | null;
  finish_before: string | null;
  finish_after: string | null;
}

export interface AppNotification {
  id: string;
  kind: string;
  level: 'info' | 'warning' | 'critical';
  message: string;
  link: string | null;
  created_at: string;
  read: boolean;
}

export interface Transfer {
  id: string;
  amount: string;
  date: string;
  from_account: string;
  to_account: string;
  notes: string | null;
}
