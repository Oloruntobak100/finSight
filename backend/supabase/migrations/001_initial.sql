-- FinSight AI initial schema

-- Users profile (extends Supabase auth.users)
CREATE TABLE IF NOT EXISTS public.users (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT,
  full_name TEXT,
  country TEXT,
  currency TEXT DEFAULT 'USD',
  plan_tier TEXT DEFAULT 'free',
  onboarded_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.connected_accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  account_name TEXT,
  account_type TEXT,
  access_token_encrypted TEXT,
  refresh_token_encrypted TEXT,
  token_expires_at TIMESTAMPTZ,
  realm_id TEXT,
  tenant_id TEXT,
  external_account_id TEXT,
  last_synced_at TIMESTAMPTZ,
  status TEXT DEFAULT 'active',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  account_id UUID REFERENCES public.connected_accounts(id) ON DELETE SET NULL,
  transaction_date DATE NOT NULL,
  description TEXT,
  merchant_name TEXT,
  category TEXT,
  sub_category TEXT,
  amount NUMERIC NOT NULL,
  currency TEXT DEFAULT 'USD',
  amount_usd NUMERIC,
  transaction_type TEXT NOT NULL,
  source_provider TEXT NOT NULL,
  external_id TEXT NOT NULL,
  is_recurring BOOLEAN DEFAULT FALSE,
  raw_metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(source_provider, external_id, user_id)
);

CREATE TABLE IF NOT EXISTS public.user_category_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  merchant_pattern TEXT NOT NULL,
  assigned_category TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, merchant_pattern)
);

CREATE TABLE IF NOT EXISTS public.financial_metrics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,
  total_income NUMERIC DEFAULT 0,
  total_expenses NUMERIC DEFAULT 0,
  net_cash_flow NUMERIC DEFAULT 0,
  savings_rate NUMERIC,
  burn_rate NUMERIC,
  calculated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.forecasts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  forecast_date DATE NOT NULL,
  horizon_days INT NOT NULL,
  predicted_income NUMERIC DEFAULT 0,
  predicted_expenses NUMERIC DEFAULT 0,
  projected_balance NUMERIC DEFAULT 0,
  confidence_score NUMERIC,
  model_version TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.ai_insights (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  insight_type TEXT NOT NULL,
  insight_text TEXT NOT NULL,
  supporting_data JSONB,
  generated_at TIMESTAMPTZ DEFAULT NOW(),
  is_dismissed BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS public.chat_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  title TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  last_message_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.chat_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  context_snapshot JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT,
  is_read BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.oauth_audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  event TEXT NOT NULL,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON public.transactions(user_id, transaction_date DESC);
CREATE INDEX IF NOT EXISTS idx_connected_accounts_user ON public.connected_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON public.chat_messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_financial_metrics_user ON public.financial_metrics(user_id, calculated_at DESC);

-- RLS
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.connected_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_category_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.financial_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.forecasts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_insights ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.oauth_audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY users_self ON public.users FOR ALL USING (id = auth.uid());

CREATE POLICY connected_accounts_self ON public.connected_accounts FOR ALL USING (user_id = auth.uid());
CREATE POLICY transactions_self ON public.transactions FOR ALL USING (user_id = auth.uid());
CREATE POLICY user_category_rules_self ON public.user_category_rules FOR ALL USING (user_id = auth.uid());
CREATE POLICY financial_metrics_self ON public.financial_metrics FOR ALL USING (user_id = auth.uid());
CREATE POLICY forecasts_self ON public.forecasts FOR ALL USING (user_id = auth.uid());
CREATE POLICY ai_insights_self ON public.ai_insights FOR ALL USING (user_id = auth.uid());
CREATE POLICY chat_sessions_self ON public.chat_sessions FOR ALL USING (user_id = auth.uid());
CREATE POLICY notifications_self ON public.notifications FOR ALL USING (user_id = auth.uid());
CREATE POLICY oauth_audit_log_self ON public.oauth_audit_log FOR ALL USING (user_id = auth.uid());

CREATE POLICY chat_messages_self ON public.chat_messages FOR ALL
  USING (
    session_id IN (SELECT id FROM public.chat_sessions WHERE user_id = auth.uid())
  );

-- Auto-create user profile on signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.users (id, email)
  VALUES (NEW.id, NEW.email)
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
