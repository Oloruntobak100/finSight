-- Books intelligence extensions on transactions + reconciliation + report cache

ALTER TABLE public.transactions
  ADD COLUMN IF NOT EXISTS payee_pattern TEXT,
  ADD COLUMN IF NOT EXISTS fingerprint_id UUID REFERENCES public.transaction_fingerprints(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS qb_suggestion_method TEXT,
  ADD COLUMN IF NOT EXISTS qb_confidence_reason TEXT,
  ADD COLUMN IF NOT EXISTS posting_intent TEXT CHECK (posting_intent IN ('expense', 'transfer', 'personal'));

CREATE INDEX IF NOT EXISTS idx_transactions_payee_pattern
  ON public.transactions (user_id, payee_pattern)
  WHERE payee_pattern IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_transactions_fingerprint
  ON public.transactions (fingerprint_id)
  WHERE fingerprint_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.reconciliation_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,
  summary JSONB NOT NULL DEFAULT '{}',
  matched JSONB NOT NULL DEFAULT '[]',
  unmatched_bank JSONB NOT NULL DEFAULT '[]',
  unmatched_qb JSONB NOT NULL DEFAULT '[]',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_runs_user
  ON public.reconciliation_runs (user_id, created_at DESC);

ALTER TABLE public.reconciliation_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY reconciliation_runs_user ON public.reconciliation_runs
  FOR ALL USING (auth.uid() = user_id);

CREATE TABLE IF NOT EXISTS public.qb_report_cache (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  report_type TEXT NOT NULL,
  params_hash TEXT NOT NULL,
  data JSONB NOT NULL DEFAULT '{}',
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (user_id, report_type, params_hash)
);

CREATE INDEX IF NOT EXISTS idx_qb_report_cache_user
  ON public.qb_report_cache (user_id, report_type);

ALTER TABLE public.qb_report_cache ENABLE ROW LEVEL SECURITY;

CREATE POLICY qb_report_cache_user ON public.qb_report_cache
  FOR ALL USING (auth.uid() = user_id);
