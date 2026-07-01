-- =============================================================================
-- FinSight: reset sandbox financial data (keep connections & mapping structure)
-- =============================================================================
-- Run in Supabase Dashboard → SQL Editor (uses service role; bypasses RLS).
--
-- REMOVES:
--   - All transactions (synthetic + Mono imports, including archived)
--   - Reconciliation runs/items/adjustments/outstanding/audit
--   - Books learning (fingerprints, posting memory, posting decisions)
--   - Synthetic feed run history
--   - Opening balance anchors on bank mappings
--   - Cached QB COA / vendors / customers / reports / metrics
--
-- KEEPS:
--   - auth.users, public.users
--   - connected_accounts (Mono / QuickBooks links)
--   - qb_account_mappings (category + bank links — re-sync COA & re-map bank after)
--   - user_category_rules, automation settings
--   - synthetic_feed_profiles (persona reset to small-volume draft)
--
-- After running:
--   1. Books → Sync chart of accounts (new QB sandbox)
--   2. Books → Mappings → confirm Access Bank → QB bank account
--   3. Data Feed → Fill history (e.g. Dec 2025) with count = 20 (not default ~500)
--   4. Books → Mappings → opening balance ₦2,000,000 as-of day before first txn
--   5. Books → post queue once
--   6. Bank Reconciliation → Dec period
--   7. Enable live drip only after history test passes
-- =============================================================================

DO $$
DECLARE
  v_user_id UUID;
  v_email   TEXT := 'kaytoba49@gmail.com';  -- ← change if needed
  v_deleted_txns INT;
BEGIN
  SELECT id INTO v_user_id FROM auth.users WHERE email = v_email;
  IF v_user_id IS NULL THEN
    RAISE EXCEPTION 'User not found for email: %', v_email;
  END IF;

  RAISE NOTICE 'Resetting sandbox financial data for user % (%)', v_email, v_user_id;

  -- RAG / audit (delete before transactions; posting_memory refs decisions)
  DELETE FROM public.posting_memory WHERE user_id = v_user_id;

  -- Reconciliation module (child tables cascade from runs)
  DELETE FROM public.reconciliation_runs WHERE user_id = v_user_id;
  DELETE FROM public.reconciliation_timing_patterns WHERE user_id = v_user_id;

  -- Transactions (+ posting_decisions / posting_adjustments via ON DELETE CASCADE)
  DELETE FROM public.transactions WHERE user_id = v_user_id;
  GET DIAGNOSTICS v_deleted_txns = ROW_COUNT;
  RAISE NOTICE 'Deleted % transaction row(s)', v_deleted_txns;

  -- Learned posting patterns (no remaining txn FKs)
  DELETE FROM public.transaction_fingerprints WHERE user_id = v_user_id;

  -- Synthetic feed audit log
  DELETE FROM public.synthetic_feed_runs WHERE user_id = v_user_id;

  -- Pause live drip; small-volume defaults for easier debugging
  UPDATE public.synthetic_feed_profiles
  SET
    live_feed_enabled   = FALSE,
    historical_start    = NULL,
    historical_end      = NULL,
    last_backfill_at    = NULL,
    last_live_run_at    = NULL,
    next_live_run_at    = NULL,
    status              = 'draft',
    daily_tx_target     = 10,
    daily_tx_min        = 5,
    daily_tx_max        = 15,
    updated_at          = NOW()
  WHERE user_id = v_user_id;

  -- Opening balance (QB sandbox was cleared separately)
  UPDATE public.qb_account_mappings
  SET
    opening_balance_amount       = NULL,
    opening_balance_as_of        = NULL,
    opening_balance_qb_journal_id = NULL,
    opening_balance_posted_at    = NULL,
    updated_at                   = NOW()
  WHERE user_id = v_user_id;

  -- Analytics & QB mirrors (re-sync from Books after QB reconnect)
  DELETE FROM public.financial_metrics WHERE user_id = v_user_id;
  DELETE FROM public.forecasts WHERE user_id = v_user_id;
  DELETE FROM public.ai_insights WHERE user_id = v_user_id;
  DELETE FROM public.qb_report_cache WHERE user_id = v_user_id;
  DELETE FROM public.qb_chart_of_accounts WHERE user_id = v_user_id;
  DELETE FROM public.qb_vendors WHERE user_id = v_user_id;
  DELETE FROM public.qb_customers WHERE user_id = v_user_id;

  RAISE NOTICE 'Sandbox financial reset complete for %', v_email;
END $$;

-- Optional: verify counts are zero
-- SELECT 'transactions' AS tbl, COUNT(*) FROM public.transactions WHERE user_id = (SELECT id FROM auth.users WHERE email = 'kaytoba49@gmail.com')
-- UNION ALL
-- SELECT 'reconciliation_runs', COUNT(*) FROM public.reconciliation_runs WHERE user_id = (SELECT id FROM auth.users WHERE email = 'kaytoba49@gmail.com');
