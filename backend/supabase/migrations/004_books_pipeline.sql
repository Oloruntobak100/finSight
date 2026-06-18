-- Books Pipeline: QuickBooks sync fields on transactions + COA cache + mappings

ALTER TABLE public.transactions
  ADD COLUMN IF NOT EXISTS qb_sync_status TEXT,
  ADD COLUMN IF NOT EXISTS qb_entity_id TEXT,
  ADD COLUMN IF NOT EXISTS qb_entity_type TEXT,
  ADD COLUMN IF NOT EXISTS qb_account_id TEXT,
  ADD COLUMN IF NOT EXISTS qb_account_name TEXT,
  ADD COLUMN IF NOT EXISTS qb_payment_account_id TEXT,
  ADD COLUMN IF NOT EXISTS qb_confidence NUMERIC,
  ADD COLUMN IF NOT EXISTS qb_posting_type TEXT,
  ADD COLUMN IF NOT EXISTS qb_posted_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS qb_error TEXT;

CREATE INDEX IF NOT EXISTS idx_transactions_qb_sync_status
  ON public.transactions (user_id, qb_sync_status)
  WHERE qb_sync_status IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.qb_chart_of_accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  realm_id TEXT NOT NULL,
  qb_account_id TEXT NOT NULL,
  name TEXT NOT NULL,
  account_type TEXT,
  account_sub_type TEXT,
  active BOOLEAN DEFAULT TRUE,
  synced_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (user_id, qb_account_id)
);

CREATE INDEX IF NOT EXISTS idx_qb_coa_user_type
  ON public.qb_chart_of_accounts (user_id, account_type);

CREATE TABLE IF NOT EXISTS public.qb_account_mappings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  mapping_type TEXT NOT NULL CHECK (mapping_type IN ('bank_account', 'category')),
  finsight_key TEXT NOT NULL,
  qb_account_id TEXT NOT NULL,
  qb_account_name TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (user_id, mapping_type, finsight_key)
);

CREATE INDEX IF NOT EXISTS idx_qb_mappings_user
  ON public.qb_account_mappings (user_id, mapping_type);

ALTER TABLE public.qb_chart_of_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.qb_account_mappings ENABLE ROW LEVEL SECURITY;

CREATE POLICY qb_coa_user ON public.qb_chart_of_accounts
  FOR ALL USING (auth.uid() = user_id);

CREATE POLICY qb_mappings_user ON public.qb_account_mappings
  FOR ALL USING (auth.uid() = user_id);
