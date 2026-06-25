-- Audit log for every suggest/approve/edit/reject/auto posting decision

CREATE TABLE IF NOT EXISTS public.posting_decisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  transaction_id UUID NOT NULL REFERENCES public.transactions(id) ON DELETE CASCADE,
  fingerprint_id UUID REFERENCES public.transaction_fingerprints(id) ON DELETE SET NULL,
  suggested_account_id TEXT,
  suggested_account_name TEXT,
  final_account_id TEXT,
  final_account_name TEXT,
  was_accepted BOOLEAN NOT NULL DEFAULT FALSE,
  edit_made BOOLEAN NOT NULL DEFAULT FALSE,
  confidence_at_time NUMERIC,
  method TEXT NOT NULL CHECK (method IN ('rule', 'fingerprint', 'rag', 'llm', 'auto', 'manual')),
  reason_text TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_posting_decisions_user
  ON public.posting_decisions (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_posting_decisions_txn
  ON public.posting_decisions (transaction_id);

CREATE INDEX IF NOT EXISTS idx_posting_decisions_fingerprint
  ON public.posting_decisions (fingerprint_id);

ALTER TABLE public.posting_decisions ENABLE ROW LEVEL SECURITY;

CREATE POLICY posting_decisions_user ON public.posting_decisions
  FOR ALL USING (auth.uid() = user_id);
