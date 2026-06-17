-- Store Plaid /transactions/sync cursor per connected bank Item
ALTER TABLE public.connected_accounts
  ADD COLUMN IF NOT EXISTS plaid_sync_cursor TEXT;
