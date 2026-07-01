"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { PageLoader } from "@/components/ui/page-loader";
import { Spinner } from "@/components/ui/spinner";
import { ApiError } from "@/lib/api";
import {
  createReconciliationRun,
  getReconciliationSetup,
  previewReconciliationBalances,
  type ReconciliationBankOption,
} from "@/lib/reconciliation";
import { formatCurrency } from "@/lib/utils";

const selectClass =
  "mt-1 block min-w-[10rem] rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-white";

export default function ReconciliationSetupPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [banks, setBanks] = useState<ReconciliationBankOption[]>([]);
  const [qbBanks, setQbBanks] = useState<{ qb_account_id: string; name: string }[]>([]);
  const [monoAccountId, setMonoAccountId] = useState("");
  const [qbBankAccountId, setQbBankAccountId] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [preview, setPreview] = useState<{
    mono: number;
    qbo: number;
    variance: number;
    currency: string;
    monoSource: string;
    qboAsOf?: string;
    openingWarning?: string | null;
  } | null>(null);

  useEffect(() => {
    getReconciliationSetup()
      .then((setup) => {
        setBanks(setup.bank_accounts);
        setQbBanks(setup.qb_bank_accounts);
        setPeriodStart(setup.default_period_start);
        setPeriodEnd(setup.default_period_end);
        if (setup.bank_accounts.length === 1) {
          const b = setup.bank_accounts[0];
          setMonoAccountId(b.id);
          if (b.qb_account_id) setQbBankAccountId(b.qb_account_id);
        }
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load setup"))
      .finally(() => setLoading(false));
  }, []);

  const loadPreview = useCallback(async () => {
    if (!monoAccountId || !qbBankAccountId || !periodEnd) return;
    try {
      const p = await previewReconciliationBalances({
        monoAccountId,
        qbBankAccountId,
        periodEnd,
      });
      setPreview({
        mono: p.mono_closing_balance,
        qbo: p.qbo_book_balance,
        variance: p.raw_variance,
        currency: p.currency,
        monoSource: p.mono_balance_source,
        qboAsOf: p.qbo_balance_as_of_date,
        openingWarning: p.opening_balance_warning,
      });
    } catch {
      setPreview(null);
    }
  }, [monoAccountId, qbBankAccountId, periodEnd]);

  useEffect(() => {
    void loadPreview();
  }, [loadPreview]);

  const handleBankChange = (id: string) => {
    setMonoAccountId(id);
    const bank = banks.find((b) => b.id === id);
    if (bank?.qb_account_id) setQbBankAccountId(bank.qb_account_id);
  };

  async function startMatching() {
    if (!monoAccountId || !qbBankAccountId) {
      setError("Select both a bank and QuickBooks account");
      return;
    }
    setRunning(true);
    setError(null);
    setStage("Fetching bank data…");
    try {
      setStage("Fetching QuickBooks data…");
      await new Promise((r) => setTimeout(r, 300));
      setStage("Running matching engine (large periods may take 1–3 minutes)…");
      const run = await createReconciliationRun({
        mono_account_id: monoAccountId,
        qb_bank_account_id: qbBankAccountId,
        period_start: periodStart,
        period_end: periodEnd,
      });
      router.push(`/reconciliation/runs/${run.id}/matching`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to start matching");
      setStage(null);
    } finally {
      setRunning(false);
    }
  }

  if (loading) return <PageLoader message="Loading reconciliation setup…" />;

  return (
    <div className="page-enter space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Bank Reconciliation</h1>
        <p className="text-slate-400">
          Step 1 — Setup. Compare bank feed activity against QuickBooks bank account postings.
        </p>
      </div>

      <Card className="border-slate-800 bg-slate-900/50">
        <CardHeader>
          <CardTitle className="text-base">Transaction Matching — Setup</CardTitle>
        </CardHeader>
        <div className="space-y-4 px-6 pb-6">
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm text-slate-400">
              Bank account
              <select value={monoAccountId} onChange={(e) => handleBankChange(e.target.value)} className={selectClass}>
                <option value="">Select bank…</option>
                {banks.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.account_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm text-slate-400">
              QuickBooks account
              <select
                value={qbBankAccountId}
                onChange={(e) => setQbBankAccountId(e.target.value)}
                className={selectClass}
              >
                <option value="">Select account…</option>
                {qbBanks.map((a) => (
                  <option key={a.qb_account_id} value={a.qb_account_id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm text-slate-400">
              Period from
              <input type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} className={selectClass} />
            </label>
            <label className="text-sm text-slate-400">
              Period to
              <input type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} className={selectClass} />
            </label>
          </div>

          {preview && (
            <div className="space-y-3">
              {preview.openingWarning && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
                  {preview.openingWarning}{" "}
                  <Link href="/books/mappings" className="underline">
                    Set opening balance
                  </Link>
                </div>
              )}
              <div className="grid gap-3 rounded-lg border border-slate-800 bg-slate-900/40 p-4 sm:grid-cols-3">
                <div>
                  <p className="text-xs text-slate-500">Bank closing ({preview.monoSource})</p>
                  <p className="text-lg font-semibold text-white">{formatCurrency(preview.mono, preview.currency)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">
                    QuickBooks book balance
                    {preview.qboAsOf ? ` (as of ${preview.qboAsOf})` : ""}
                  </p>
                  <p className="text-lg font-semibold text-white">{formatCurrency(preview.qbo, preview.currency)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Raw variance</p>
                  <p className={`text-lg font-semibold ${preview.variance === 0 ? "text-emerald-400" : "text-amber-400"}`}>
                    {formatCurrency(preview.variance, preview.currency)}
                  </p>
                </div>
              </div>
            </div>
          )}

          {!monoAccountId || !qbBankAccountId ? (
            <p className="text-sm text-amber-400">
              Map your bank under{" "}
              <Link href="/books/mappings" className="underline">
                Books → Mappings
              </Link>{" "}
              if QuickBooks account is not auto-filled.
            </p>
          ) : null}

          <Button onClick={startMatching} disabled={running}>
            {running ? <Spinner size="sm" className="mr-2" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            Start Transaction Matching
          </Button>
          {stage && <p className="text-sm text-blue-300">{stage}</p>}
        </div>
      </Card>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">{error}</div>
      )}
    </div>
  );
}
