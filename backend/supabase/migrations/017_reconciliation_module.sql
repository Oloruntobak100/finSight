-- Bank reconciliation module: structured runs, items, adjustments, outstanding, audit

-- Extend reconciliation_runs (legacy JSON columns retained for old runs)
ALTER TABLE public.reconciliation_runs
  ADD COLUMN IF NOT EXISTS mono_account_id UUID REFERENCES public.connected_accounts(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS qb_bank_account_id TEXT,
  ADD COLUMN IF NOT EXISTS mono_closing_balance NUMERIC,
  ADD COLUMN IF NOT EXISTS qbo_book_balance NUMERIC,
  ADD COLUMN IF NOT EXISTS mono_balance_source TEXT,
  ADD COLUMN IF NOT EXISTS adjusted_bank_balance NUMERIC,
  ADD COLUMN IF NOT EXISTS adjusted_book_balance NUMERIC,
  ADD COLUMN IF NOT EXISTS variance NUMERIC,
  ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'DRAFT',
  ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS reviewed_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS self_approved BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS snapshot_mono_data JSONB DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS snapshot_qbo_data JSONB DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE public.reconciliation_runs
  DROP CONSTRAINT IF EXISTS reconciliation_runs_status_check;

ALTER TABLE public.reconciliation_runs
  ADD CONSTRAINT reconciliation_runs_status_check
  CHECK (status IN ('DRAFT', 'IN_REVIEW', 'ADJUSTED', 'APPROVED', 'LOCKED'));

CREATE INDEX IF NOT EXISTS idx_reconciliation_runs_account_period
  ON public.reconciliation_runs (user_id, mono_account_id, period_end DESC);

CREATE TABLE IF NOT EXISTS public.reconciliation_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES public.reconciliation_runs(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  source TEXT NOT NULL CHECK (source IN ('MONO', 'QBO', 'BOTH')),
  match_status TEXT NOT NULL,
  mono_transaction_id UUID REFERENCES public.transactions(id) ON DELETE SET NULL,
  qbo_entity_id TEXT,
  qbo_entity_type TEXT,
  paired_mono_item_id UUID REFERENCES public.reconciliation_items(id) ON DELETE SET NULL,
  paired_qbo_item_id UUID REFERENCES public.reconciliation_items(id) ON DELETE SET NULL,
  match_score NUMERIC DEFAULT 0,
  amount NUMERIC NOT NULL DEFAULT 0,
  currency TEXT DEFAULT 'NGN',
  transaction_date DATE,
  direction TEXT CHECK (direction IN ('in', 'out')),
  payee TEXT,
  reference TEXT,
  narration TEXT,
  manually_matched_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
  manually_matched_at TIMESTAMPTZ,
  carry_forward BOOLEAN DEFAULT FALSE,
  prior_run_id UUID REFERENCES public.reconciliation_runs(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_items_run_status
  ON public.reconciliation_items (run_id, match_status);

CREATE INDEX IF NOT EXISTS idx_reconciliation_items_mono
  ON public.reconciliation_items (mono_transaction_id)
  WHERE mono_transaction_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.reconciliation_adjustments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES public.reconciliation_runs(id) ON DELETE CASCADE,
  item_id UUID REFERENCES public.reconciliation_items(id) ON DELETE SET NULL,
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  adjustment_type TEXT NOT NULL,
  affects_side TEXT NOT NULL CHECK (affects_side IN ('BANK', 'BOOK')),
  amount NUMERIC NOT NULL DEFAULT 0,
  journal_entry_required BOOLEAN DEFAULT FALSE,
  journal_entry_posted BOOLEAN DEFAULT FALSE,
  journal_entry_id TEXT,
  offset_qb_account_id TEXT,
  offset_qb_account_name TEXT,
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_adjustments_run
  ON public.reconciliation_adjustments (run_id);

CREATE TABLE IF NOT EXISTS public.reconciliation_outstanding_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  mono_account_id UUID REFERENCES public.connected_accounts(id) ON DELETE SET NULL,
  qb_bank_account_id TEXT,
  originating_run_id UUID NOT NULL REFERENCES public.reconciliation_runs(id) ON DELETE CASCADE,
  resolved_run_id UUID REFERENCES public.reconciliation_runs(id) ON DELETE SET NULL,
  reconciliation_item_id UUID REFERENCES public.reconciliation_items(id) ON DELETE SET NULL,
  item_type TEXT NOT NULL CHECK (item_type IN ('DEPOSIT_IN_TRANSIT', 'OUTSTANDING_PAYMENT')),
  amount NUMERIC NOT NULL,
  currency TEXT DEFAULT 'NGN',
  description TEXT,
  original_date DATE,
  status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLEARED', 'VOIDED')),
  cleared_date DATE,
  mono_transaction_id UUID REFERENCES public.transactions(id) ON DELETE SET NULL,
  qbo_entity_id TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_outstanding_open
  ON public.reconciliation_outstanding_items (user_id, mono_account_id, status)
  WHERE status = 'OPEN';

CREATE TABLE IF NOT EXISTS public.reconciliation_audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES public.reconciliation_runs(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  actor_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  action TEXT NOT NULL,
  before_state JSONB,
  after_state JSONB,
  comment TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_audit_run
  ON public.reconciliation_audit_log (run_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.reconciliation_timing_patterns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  payee_pattern TEXT NOT NULL,
  auto_match_status TEXT NOT NULL DEFAULT 'TIMING_DIFFERENCE',
  hit_count INT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (user_id, payee_pattern)
);

ALTER TABLE public.reconciliation_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reconciliation_adjustments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reconciliation_outstanding_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reconciliation_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reconciliation_timing_patterns ENABLE ROW LEVEL SECURITY;

CREATE POLICY reconciliation_items_user ON public.reconciliation_items
  FOR ALL USING (auth.uid() = user_id);

CREATE POLICY reconciliation_adjustments_user ON public.reconciliation_adjustments
  FOR ALL USING (auth.uid() = user_id);

CREATE POLICY reconciliation_outstanding_user ON public.reconciliation_outstanding_items
  FOR ALL USING (auth.uid() = user_id);

CREATE POLICY reconciliation_audit_user ON public.reconciliation_audit_log
  FOR ALL USING (auth.uid() = user_id);

CREATE POLICY reconciliation_timing_user ON public.reconciliation_timing_patterns
  FOR ALL USING (auth.uid() = user_id);
