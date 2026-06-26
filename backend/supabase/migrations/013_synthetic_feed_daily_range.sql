-- Daily transaction target as min/max range instead of single fixed value

ALTER TABLE public.synthetic_feed_profiles
  ADD COLUMN IF NOT EXISTS daily_tx_min INT NOT NULL DEFAULT 8,
  ADD COLUMN IF NOT EXISTS daily_tx_max INT NOT NULL DEFAULT 20;

UPDATE public.synthetic_feed_profiles
SET
  daily_tx_min = GREATEST(1, daily_tx_target - 7),
  daily_tx_max = LEAST(500, daily_tx_target + 7)
WHERE daily_tx_target IS NOT NULL;
