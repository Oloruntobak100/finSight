export type PlanTier = 'free' | 'pro' | 'business';

export type AccountProvider = 'plaid' | 'mono' | 'quickbooks' | 'xero';

export type AccountStatus = 'active' | 'needs_reauth' | 'syncing' | 'disconnected';

export type TransactionType = 'debit' | 'credit';

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  country: string | null;
  currency: string;
  plan_tier: PlanTier;
  onboarded_at: string | null;
  created_at: string;
}

export interface ConnectedAccount {
  id: string;
  user_id: string;
  provider: AccountProvider;
  account_name: string;
  account_type: string | null;
  external_account_id: string | null;
  last_synced_at: string | null;
  status: AccountStatus;
  created_at: string;
}

export interface Transaction {
  id: string;
  user_id: string;
  account_id: string | null;
  transaction_date: string;
  description: string | null;
  merchant_name: string | null;
  category: string | null;
  sub_category: string | null;
  amount: number;
  currency: string;
  amount_usd: number | null;
  transaction_type: TransactionType;
  source_provider: string;
  external_id: string;
  is_recurring: boolean;
  created_at: string;
}

export interface FinancialMetrics {
  id: string;
  user_id: string;
  period_start: string;
  period_end: string;
  total_income: number;
  total_expenses: number;
  net_cash_flow: number;
  savings_rate: number | null;
  burn_rate: number | null;
  calculated_at: string;
}

export interface Forecast {
  id: string;
  user_id: string;
  forecast_date: string;
  horizon_days: number;
  predicted_income: number;
  predicted_expenses: number;
  projected_balance: number;
  confidence_score: number | null;
  model_version: string | null;
  created_at: string;
}

export interface AIInsight {
  id: string;
  user_id: string;
  insight_type: string;
  insight_text: string;
  supporting_data: Record<string, unknown> | null;
  generated_at: string;
  is_dismissed: boolean;
}

export interface ChatSession {
  id: string;
  user_id: string;
  title: string | null;
  created_at: string;
  last_message_at: string | null;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  context_snapshot: Record<string, unknown> | null;
  created_at: string;
}

export interface SubscriptionItem {
  merchant_name: string;
  amount: number;
  currency: string;
  frequency: string;
  annual_cost: number;
  transaction_count: number;
}

export interface PaginatedTransactions {
  items: Transaction[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}
