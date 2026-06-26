-- Synthetic Data Feed: profiles, run audit log, transaction flags

ALTER TABLE public.transactions
  ADD COLUMN IF NOT EXISTS is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_transactions_is_synthetic
  ON public.transactions (user_id, is_synthetic)
  WHERE archived_at IS NULL;

CREATE TABLE IF NOT EXISTS public.synthetic_feed_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  account_id UUID NOT NULL REFERENCES public.connected_accounts(id) ON DELETE CASCADE,
  persona_type TEXT NOT NULL DEFAULT 'individual',
  persona_config JSONB NOT NULL DEFAULT '{}'::jsonb,
  historical_start DATE NULL,
  historical_end DATE NULL,
  live_feed_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  live_interval_hours INT NOT NULL DEFAULT 6,
  daily_tx_target INT NOT NULL DEFAULT 15,
  auto_classify BOOLEAN NOT NULL DEFAULT TRUE,
  status TEXT NOT NULL DEFAULT 'draft',
  last_backfill_at TIMESTAMPTZ NULL,
  next_live_run_at TIMESTAMPTZ NULL,
  last_live_run_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (user_id, account_id)
);

CREATE TABLE IF NOT EXISTS public.synthetic_feed_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID NOT NULL REFERENCES public.synthetic_feed_profiles(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  account_id UUID NOT NULL REFERENCES public.connected_accounts(id) ON DELETE CASCADE,
  run_type TEXT NOT NULL,
  transactions_created INT NOT NULL DEFAULT 0,
  transactions_archived INT NOT NULL DEFAULT 0,
  persona_snapshot JSONB NULL,
  status TEXT NOT NULL DEFAULT 'running',
  error TEXT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_synthetic_feed_profiles_live
  ON public.synthetic_feed_profiles (live_feed_enabled, next_live_run_at)
  WHERE live_feed_enabled = TRUE;

CREATE INDEX IF NOT EXISTS idx_synthetic_feed_runs_profile
  ON public.synthetic_feed_runs (profile_id, started_at DESC);

ALTER TABLE public.synthetic_feed_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.synthetic_feed_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY synthetic_feed_profiles_self ON public.synthetic_feed_profiles
  FOR ALL USING (user_id = auth.uid());

CREATE POLICY synthetic_feed_runs_self ON public.synthetic_feed_runs
  FOR ALL USING (user_id = auth.uid());
