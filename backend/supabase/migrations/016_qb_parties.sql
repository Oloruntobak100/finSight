-- QuickBooks Vendor / Customer cache and transaction party mapping

CREATE TABLE IF NOT EXISTS public.qb_vendors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  realm_id TEXT NOT NULL,
  qb_vendor_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  active BOOLEAN DEFAULT TRUE,
  synced_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (user_id, qb_vendor_id)
);

CREATE INDEX IF NOT EXISTS idx_qb_vendors_user
  ON public.qb_vendors (user_id, display_name);

CREATE TABLE IF NOT EXISTS public.qb_customers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  realm_id TEXT NOT NULL,
  qb_customer_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  active BOOLEAN DEFAULT TRUE,
  synced_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (user_id, qb_customer_id)
);

CREATE INDEX IF NOT EXISTS idx_qb_customers_user
  ON public.qb_customers (user_id, display_name);

ALTER TABLE public.transactions
  ADD COLUMN IF NOT EXISTS qb_party_id TEXT,
  ADD COLUMN IF NOT EXISTS qb_party_type TEXT,
  ADD COLUMN IF NOT EXISTS qb_party_name TEXT,
  ADD COLUMN IF NOT EXISTS qb_doc_number TEXT;

ALTER TABLE public.transactions
  DROP CONSTRAINT IF EXISTS transactions_qb_party_type_check;

ALTER TABLE public.transactions
  ADD CONSTRAINT transactions_qb_party_type_check
  CHECK (qb_party_type IS NULL OR qb_party_type IN ('Vendor', 'Customer'));

ALTER TABLE public.transaction_fingerprints
  ADD COLUMN IF NOT EXISTS qb_party_id TEXT,
  ADD COLUMN IF NOT EXISTS qb_party_type TEXT,
  ADD COLUMN IF NOT EXISTS qb_party_name TEXT;

ALTER TABLE public.transaction_fingerprints
  DROP CONSTRAINT IF EXISTS transaction_fingerprints_qb_party_type_check;

ALTER TABLE public.transaction_fingerprints
  ADD CONSTRAINT transaction_fingerprints_qb_party_type_check
  CHECK (qb_party_type IS NULL OR qb_party_type IN ('Vendor', 'Customer'));

ALTER TABLE public.qb_vendors ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.qb_customers ENABLE ROW LEVEL SECURITY;

CREATE POLICY qb_vendors_user ON public.qb_vendors
  FOR ALL USING (auth.uid() = user_id);

CREATE POLICY qb_customers_user ON public.qb_customers
  FOR ALL USING (auth.uid() = user_id);
