"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { approveTransaction, postTransaction, runReconciliation } from "@/lib/books";
import { ApiError } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";

type Tab = "matched" | "unmatched_bank" | "unmatched_qb";

interface ReconResult {
  id?: string;
  summary: {
    matched_count: number;
    unmatched_bank_count: number;
    unmatched_qb_count: number;
    match_rate: number;
    variance: number;
    message?: string;
  };
  matched: Array<{ bank: Record<string, unknown>; qb: Record<string, unknown> }>;
  unmatched_bank: Array<Record<string, unknown>>;
  unmatched_qb: Array<Record<string, unknown>>;
}

export default function ReconciliationPage() {
  const [tab, setTab] = useState<Tab>("matched");
  const [start, setStart] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
  });
  const [end, setEnd] = useState(() => new Date().toISOString().slice(0, 10));
  const [result, setResult] = useState<ReconResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = (await runReconciliation(start, end)) as ReconResult;
      setResult(data);
      if (typeof window !== "undefined") {
        localStorage.setItem("finsight-last-recon", JSON.stringify(data));
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Reconciliation failed");
    } finally {
      setLoading(false);
    }
  }, [start, end]);

  useEffect(() => {
    const raw = localStorage.getItem("finsight-last-recon");
    if (raw) {
      try {
        setResult(JSON.parse(raw));
      } catch {
        /* ignore */
      }
    }
  }, []);

  async function postFromBank(txnId: string, qbAccountId?: string) {
    if (!qbAccountId) {
      await postTransaction(txnId);
    } else {
      await approveTransaction(txnId, qbAccountId, true);
    }
    await run();
  }

  const summary = result?.summary;

  return (
    <div className="page-enter space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Books vs Bank Check</h1>
        <p className="text-slate-400">Compare your bank transactions with QuickBooks postings.</p>
      </div>

      <Card className="border-slate-800 bg-slate-900/50">
        <CardHeader>
          <CardTitle className="text-base">Run check</CardTitle>
        </CardHeader>
        <div className="flex flex-wrap items-end gap-3 px-6 pb-6">
          <label className="text-sm text-slate-400">
            From
            <input
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className="mt-1 block rounded border border-slate-700 bg-slate-900 px-2 py-1 text-white"
            />
          </label>
          <label className="text-sm text-slate-400">
            To
            <input
              type="date"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              className="mt-1 block rounded border border-slate-700 bg-slate-900 px-2 py-1 text-white"
            />
          </label>
          <Button onClick={run} disabled={loading}>
            {loading ? <Spinner size="sm" className="mr-2" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            Run
          </Button>
        </div>
      </Card>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {summary && (
        <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3 text-sm text-slate-300">
          {summary.matched_count} of{" "}
          {summary.matched_count + summary.unmatched_bank_count} bank debits matched (
          {(summary.match_rate * 100).toFixed(1)}%). Variance:{" "}
          {formatCurrency(summary.variance, "NGN")}
          {summary.message && <p className="mt-2 text-amber-400">{summary.message}</p>}
        </div>
      )}

      {result && (
        <>
          <div className="flex gap-2">
            {(
              [
                ["matched", `Matched (${summary?.matched_count ?? 0})`],
                ["unmatched_bank", `Unmatched bank (${summary?.unmatched_bank_count ?? 0})`],
                ["unmatched_qb", `Unmatched QB (${summary?.unmatched_qb_count ?? 0})`],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`rounded-lg px-3 py-1.5 text-sm ${
                  tab === id ? "bg-blue-600/20 text-blue-400" : "text-slate-400"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="overflow-x-auto rounded-xl border border-slate-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-left text-slate-500">
                  <th className="p-3">Date</th>
                  <th className="p-3">Description</th>
                  <th className="p-3 text-right">Amount</th>
                  <th className="p-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {tab === "matched" &&
                  result.matched.map((m, i) => {
                    const bank = m.bank as {
                      transaction_date?: string;
                      merchant_name?: string;
                      amount?: number;
                      currency?: string;
                    };
                    return (
                      <tr key={i} className="border-b border-slate-800/50">
                        <td className="p-3">{bank.transaction_date}</td>
                        <td className="p-3">{bank.merchant_name}</td>
                        <td className="p-3 text-right">
                          {formatCurrency(bank.amount ?? 0, bank.currency ?? "NGN")}
                        </td>
                        <td className="p-3 text-emerald-400">Matched</td>
                      </tr>
                    );
                  })}
                {tab === "unmatched_bank" &&
                  result.unmatched_bank.map((b) => (
                    <tr key={String(b.id)} className="border-b border-slate-800/50">
                      <td className="p-3">{String(b.transaction_date)}</td>
                      <td className="p-3">{String(b.merchant_name || b.description || "—")}</td>
                      <td className="p-3 text-right">
                        {formatCurrency(Number(b.amount) || 0, String(b.currency || "NGN"))}
                      </td>
                      <td className="p-3">
                        <Link href={`/books?status=pending`}>
                          <Button size="sm" variant="outline">
                            Review in Books
                          </Button>
                        </Link>
                      </td>
                    </tr>
                  ))}
                {tab === "unmatched_qb" &&
                  result.unmatched_qb.map((q, i) => (
                    <tr key={i} className="border-b border-slate-800/50">
                      <td className="p-3">{String(q.TxnDate || "—")}</td>
                      <td className="p-3">QBO Purchase #{String(q.Id || "—")}</td>
                      <td className="p-3 text-right">{formatCurrency(Number(q.TotalAmt) || 0, "USD")}</td>
                      <td className="p-3 text-amber-400">Manual entry?</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
