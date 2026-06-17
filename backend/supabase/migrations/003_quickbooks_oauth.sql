-- QuickBooks OAuth: refresh token expiry + one active QB connection per user
ALTER TABLE public.connected_accounts
  ADD COLUMN IF NOT EXISTS refresh_token_expires_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS idx_connected_accounts_user_quickbooks
  ON public.connected_accounts (user_id)
  WHERE provider = 'quickbooks' AND status = 'active';
