-- Learn posting kind (expense/income/transfer/fee/refund/balance_sheet) from approvals

ALTER TABLE public.transaction_fingerprints
  ADD COLUMN IF NOT EXISTS posting_kind TEXT;

ALTER TABLE public.transaction_fingerprints
  DROP CONSTRAINT IF EXISTS transaction_fingerprints_posting_kind_check;

ALTER TABLE public.transaction_fingerprints
  ADD CONSTRAINT transaction_fingerprints_posting_kind_check
  CHECK (posting_kind IS NULL OR posting_kind IN (
    'expense', 'income', 'transfer', 'fee', 'reversal', 'balance_sheet', 'refund'
  ));
