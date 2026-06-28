-- User UI preferences (column visibility, etc.)

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS ui_preferences JSONB NOT NULL DEFAULT '{}'::jsonb;
