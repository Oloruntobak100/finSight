-- Transaction fingerprints for approval learning

CREATE TABLE IF NOT EXISTS public.transaction_fingerprints (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  payee_pattern TEXT NOT NULL,
  bank_code TEXT,
  channel TEXT,
  amount_band TEXT NOT NULL,
  recurrence_count INT NOT NULL DEFAULT 0,
  last_seen_at TIMESTAMPTZ,
  qb_account_id TEXT,
  qb_account_name TEXT,
  confidence NUMERIC NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (user_id, payee_pattern, channel, amount_band)
);

CREATE INDEX IF NOT EXISTS idx_fingerprints_user
  ON public.transaction_fingerprints (user_id);

CREATE INDEX IF NOT EXISTS idx_fingerprints_lookup
  ON public.transaction_fingerprints (user_id, payee_pattern, channel, amount_band);

ALTER TABLE public.transaction_fingerprints ENABLE ROW LEVEL SECURITY;

CREATE POLICY fingerprints_user ON public.transaction_fingerprints
  FOR ALL USING (auth.uid() = user_id);
