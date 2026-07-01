-- QuickBooks reconnect: lookup prior connection by stable company realm_id

CREATE INDEX IF NOT EXISTS idx_connected_accounts_qb_realm
  ON public.connected_accounts (user_id, realm_id)
  WHERE provider = 'quickbooks' AND realm_id IS NOT NULL;
