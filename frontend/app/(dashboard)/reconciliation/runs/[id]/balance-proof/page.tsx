"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { PageLoader } from "@/components/ui/page-loader";
import { ApiError } from "@/lib/api";
import {
  getBalanceProof,
  recalculateReconciliationRun,
  type BalanceProof,
  type ReconciliationRun,
} from "@/lib/reconciliation";
import { formatCurrency } from "@/lib/utils";
import { ReconciliationRunNav } from "../run-nav";

function ProofLine({ label, amount, currency }: { label: string; amount: number; currency?: string }) {
  return (
    <div className="flex justify-between border-b border-slate-800/50 py-2 text-sm">
      <span className="text-slate-400">{label}</span>
      <span className="text-white">{formatCurrency(amount, currency ?? "NGN")}</span>
    </div>
  );
}

export default function BalanceProofPage() {
  const params = useParams();
  const runId = String(params.id);
  const [run, setRun] = useState<ReconciliationRun | null>(null);
  const [proof, setProof] = useState<BalanceProof | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await recalculateReconciliationRun(runId);
      setRun(r);
      const p = await getBalanceProof(runId);
      setProof(p.balance_proof);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load balance proof");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !proof) return <PageLoader message="Calculating balance proof…" />;

  const currency = run?.summary?.currency ?? "NGN";
  const variance = proof?.variance ?? run?.variance ?? 0;
  const blocked = Math.abs(variance) > 0.01;

  return (
    <div className="page-enter space-y-4">
      <ReconciliationRunNav runId={runId} status={run?.status} />

      <div>
        <h1 className="text-xl font-bold text-white">Balance Proof</h1>
        <p className="text-sm text-slate-500">Formal reconciliation statement — adjusted balances must agree.</p>
      </div>

      {blocked && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          Reconciliation cannot be approved while a variance exists. Review unclassified items in Transaction Matching.
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>
      )}

      {proof && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
            <h2 className="mb-3 font-semibold text-white">Bank balance (Mono)</h2>
            <ProofLine label="Mono closing balance" amount={proof.mono_closing_balance} currency={currency} />
            <ProofLine label="Plus deposits in transit" amount={proof.deposits_in_transit} currency={currency} />
            <ProofLine label="Minus outstanding payments" amount={-proof.outstanding_payments} currency={currency} />
            <ProofLine label="Bank adjustments" amount={proof.bank_adjustments} currency={currency} />
            <div className="mt-3 flex justify-between border-t border-slate-700 pt-3 font-semibold">
              <span className="text-slate-300">Adjusted bank balance</span>
              <span className="text-white">{formatCurrency(proof.adjusted_bank_balance, currency)}</span>
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
            <h2 className="mb-3 font-semibold text-white">Book balance (QuickBooks)</h2>
            <ProofLine label="QBO account balance" amount={proof.qbo_book_balance} currency={currency} />
            <ProofLine label="Minus unrecorded bank charges" amount={-proof.unrecorded_bank_charges} currency={currency} />
            <ProofLine label="Plus unrecorded bank credits" amount={proof.unrecorded_bank_credits} currency={currency} />
            <ProofLine label="Book adjustments" amount={proof.book_adjustments} currency={currency} />
            <div className="mt-3 flex justify-between border-t border-slate-700 pt-3 font-semibold">
              <span className="text-slate-300">Adjusted book balance</span>
              <span className="text-white">{formatCurrency(proof.adjusted_book_balance, currency)}</span>
            </div>
          </div>
        </div>
      )}

      <div
        className={`rounded-lg border px-4 py-3 text-center text-lg font-semibold ${
          blocked ? "border-amber-500/40 text-amber-300" : "border-emerald-500/40 text-emerald-300"
        }`}
      >
        Variance: {formatCurrency(variance, currency)}
        {!blocked && " — Balanced"}
      </div>

      <div className="flex flex-wrap gap-2">
        <Link href={`/reconciliation/runs/${runId}/matching`}>
          <Button variant="outline">← Matching</Button>
        </Link>
        <Link href={`/reconciliation/runs/${runId}/journals`}>
          <Button>Journal Entries →</Button>
        </Link>
      </div>
    </div>
  );
}
