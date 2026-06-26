-- Extend posting intent for income and fee teaching

ALTER TABLE public.transactions
  DROP CONSTRAINT IF EXISTS transactions_posting_intent_check;

ALTER TABLE public.transactions
  ADD CONSTRAINT transactions_posting_intent_check
  CHECK (posting_intent IS NULL OR posting_intent IN (
    'expense', 'income', 'transfer', 'personal', 'fee'
  ));

-- Re-queue credits previously marked skipped so they enter the income classify flow
UPDATE public.transactions
SET qb_sync_status = NULL,
    qb_confidence_reason = NULL
WHERE transaction_type = 'credit'
  AND qb_sync_status = 'skipped';
