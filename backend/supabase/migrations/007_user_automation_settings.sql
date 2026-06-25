-- User automation preferences for auto-approve and digest

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS auto_approve_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS auto_approve_threshold NUMERIC NOT NULL DEFAULT 0.90,
  ADD COLUMN IF NOT EXISTS digest_enabled BOOLEAN NOT NULL DEFAULT TRUE;
