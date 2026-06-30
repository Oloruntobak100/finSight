-- Stable bank reconnect: one logical account per external provider id per user.

CREATE UNIQUE INDEX IF NOT EXISTS idx_connected_accounts_user_provider_external
  ON public.connected_accounts (user_id, provider, external_account_id)
  WHERE external_account_id IS NOT NULL;
