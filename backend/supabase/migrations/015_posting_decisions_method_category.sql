-- Allow category/auto_detect in posting_decisions audit log (Books classify methods).

ALTER TABLE public.posting_decisions
  DROP CONSTRAINT IF EXISTS posting_decisions_method_check;

ALTER TABLE public.posting_decisions
  ADD CONSTRAINT posting_decisions_method_check
  CHECK (
    method IN (
      'rule',
      'fingerprint',
      'rag',
      'llm',
      'auto',
      'manual',
      'category',
      'auto_detect'
    )
  );
