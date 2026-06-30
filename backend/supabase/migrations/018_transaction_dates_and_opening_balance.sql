-- Transaction date discipline, posting lag, opening balances, closed-period audit

ALTER TABLE public.transactions
  ADD COLUMN IF NOT EXISTS discovered_date TIMESTAMPTZ;

UPDATE public.transactions
SET discovered_date = created_at
WHERE discovered_date IS NULL;

-- Regular column (not GENERATED): timestamptz::date is not immutable in PG.
ALTER TABLE public.transactions
  ADD COLUMN IF NOT EXISTS posting_lag_days INT;

CREATE OR REPLACE FUNCTION public.sync_transaction_posting_lag_days()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.qb_posted_at IS NOT NULL AND NEW.transaction_date IS NOT NULL THEN
    NEW.posting_lag_days := ((NEW.qb_posted_at AT TIME ZONE 'UTC')::date - NEW.transaction_date);
  ELSE
    NEW.posting_lag_days := NULL;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sync_posting_lag_days ON public.transactions;
CREATE TRIGGER trg_sync_posting_lag_days
  BEFORE INSERT OR UPDATE OF qb_posted_at, transaction_date ON public.transactions
  FOR EACH ROW
  EXECUTE FUNCTION public.sync_transaction_posting_lag_days();

UPDATE public.transactions
SET posting_lag_days = ((qb_posted_at AT TIME ZONE 'UTC')::date - transaction_date)
WHERE qb_posted_at IS NOT NULL
  AND transaction_date IS NOT NULL
  AND posting_lag_days IS NULL;

CREATE INDEX IF NOT EXISTS idx_transactions_posting_lag
  ON public.transactions (user_id, posting_lag_days)
  WHERE posting_lag_days > 7;

CREATE OR REPLACE FUNCTION public.preserve_transaction_discovered_date()
RETURNS TRIGGER AS $$
BEGIN
  IF OLD.discovered_date IS NOT NULL THEN
    NEW.discovered_date := OLD.discovered_date;
  ELSIF NEW.discovered_date IS NULL THEN
    NEW.discovered_date := COALESCE(NEW.created_at, NOW());
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_preserve_discovered_date ON public.transactions;
CREATE TRIGGER trg_preserve_discovered_date
  BEFORE UPDATE ON public.transactions
  FOR EACH ROW
  EXECUTE FUNCTION public.preserve_transaction_discovered_date();

ALTER TABLE public.qb_account_mappings
  ADD COLUMN IF NOT EXISTS opening_balance_amount NUMERIC,
  ADD COLUMN IF NOT EXISTS opening_balance_as_of DATE,
  ADD COLUMN IF NOT EXISTS opening_balance_qb_journal_id TEXT,
  ADD COLUMN IF NOT EXISTS opening_balance_posted_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS public.posting_adjustments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  transaction_id UUID NOT NULL REFERENCES public.transactions(id) ON DELETE CASCADE,
  path TEXT NOT NULL CHECK (path IN ('true_date', 'catch_up_today')),
  requested_txn_date DATE NOT NULL,
  actual_txn_date DATE NOT NULL,
  reason TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_posting_adjustments_user_txn
  ON public.posting_adjustments (user_id, transaction_id);

ALTER TABLE public.posting_adjustments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS posting_adjustments_self ON public.posting_adjustments;
CREATE POLICY posting_adjustments_self ON public.posting_adjustments
  FOR ALL USING (user_id = auth.uid());

ALTER TABLE public.reconciliation_runs
  ADD COLUMN IF NOT EXISTS qbo_balance_as_of_date DATE,
  ADD COLUMN IF NOT EXISTS opening_balance_warning TEXT;

ALTER TABLE public.reconciliation_items
  DROP CONSTRAINT IF EXISTS reconciliation_items_match_status_check;

-- match_status is validated in application code; allow new AMOUNT_MATCH_SUGGESTED
