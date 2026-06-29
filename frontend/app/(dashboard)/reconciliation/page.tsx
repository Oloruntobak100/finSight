"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { PageLoader } from "@/components/ui/page-loader";
import { Spinner } from "@/components/ui/spinner";
import {
  getReconciliationOptions,
  runReconciliation,
  type ReconciliationBankOption,
  type ReconciliationSide,
} from "@/lib/books";
import { ApiError } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";

type Tab = "matched" | "unmatched_bank" | "unmatched_qb";

interface ReconSummary {
  matched_count: number;
  unmatched_bank_count: number;
  unmatched_qb_count: number;
  match_rate: number;
  variance: number;
  side_label?: string;
  message?: string;
  filters?: {
    bank_account_id?: string | null;
    bank_account_name?: string | null;
    qb_bank_account_id?: string | null;
    qb_bank_account_name?: string | null;
  };
}

interface ReconResult {
  id?: string;
  summary: ReconSummary;
  matched: Array<{ bank: Record<string, unknown>; qb: Record<string, unknown>; qb_kind?: string }>;
  unmatched_bank: Array<Record<string, unknown>>;
  unmatched_qb: Array<Record<string, unknown> & { qb_kind?: string }>;
}

const selectClass =
  "mt-1 block min-w-[10rem] rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-white";

export default function ReconciliationPage() {
  const [tab, setTab] = useState<Tab>("matched");
  const [start, setStart] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
  });
  const [end, setEnd] = useState(() => new Date().toISOString().slice(0, 10));
  const [bankAccountId, setBankAccountId] = useState("");
  const [qbBankAccountId, setQbBankAccountId] = useState("");
  const [transactionSide, setTransactionSide] = useState<ReconciliationSide>("debit");
  const [bankAccounts, setBankAccounts] = useState<ReconciliationBankOption[]>([]);
  const [qbBankAccounts, setQbBankAccounts] = useState<{ qb_account_id: string; name: string }[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(true);
  const [result, setResult] = useState<ReconResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadOptions() {
      setOptionsLoading(true);
      try {
        const options = await getReconciliationOptions();
        if (cancelled) return;
        setBankAccounts(options.bank_accounts);
        setQbBankAccounts(options.qb_bank_accounts);
        if (options.bank_accounts.length === 1) {
          const only = options.bank_accounts[0];
          setBankAccountId(only.id);
          if (only.qb_account_id) setQbBankAccountId(only.qb_account_id);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : "Failed to load reconciliation options");
        }
      } finally {
        if (!cancelled) setOptionsLoading(false);
      }
    }
    void loadOptions();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const raw = localStorage.getItem("finsight-last-recon");
    if (raw) {
      try {
        setResult(JSON.parse(raw) as ReconResult);
      } catch {
        /* ignore */
      }
    }
  }, []);

  const handleBankChange = useCallback(
    (value: string) => {
      setBankAccountId(value);
      if (!value) return;
      const bank = bankAccounts.find((b) => b.id === value);
      if (bank?.qb_account_id) setQbBankAccountId(bank.qb_account_id);
    },
    [bankAccounts]
  );

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = (await runReconciliation({
        periodStart: start,
        periodEnd: end,
        bankAccountId: bankAccountId || undefined,
        qbBankAccountId: qbBankAccountId || undefined,
        transactionSide,
      })) as ReconResult;
      setResult(data);
      if (typeof window !== "undefined") {
        localStorage.setItem("finsight-last-recon", JSON.stringify(data));
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Reconciliation failed");
    } finally {
      setLoading(false);
    }
  }, [start, end, bankAccountId, qbBankAccountId, transactionSide]);

  const summary = result?.summary;
  const sideLabel = summary?.side_label ?? "debits";
  const selectedBank = bankAccounts.find((b) => b.id === bankAccountId);
  const missingBankMapping = Boolean(bankAccountId && selectedBank && !selectedBank.qb_account_id && !qbBankAccountId);

  if (optionsLoading) {
    return <PageLoader label="Loading reconciliation…" />;
  }

  return (
    <div className="page-enter space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Bank Reconciliation</h1>
        <p className="text-slate-400">
          Compare bank feed lines with QuickBooks for a period, bank, and account.
        </p>
      </div>

      <Card className="border-slate-800 bg-slate-900/50">
        <CardHeader>
          <CardTitle className="text-base">Run reconciliation</CardTitle>
        </CardHeader>
        <div className="space-y-4 px-6 pb-6">
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm text-slate-400">
              From
              <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className={selectClass} />
            </label>
            <label className="text-sm text-slate-400">
              To
              <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className={selectClass} />
            </label>
            <label className="text-sm text-slate-400">
              Bank
              <select value={bankAccountId} onChange={(e) => handleBankChange(e.target.value)} className={selectClass}>
                <option value="">All connected banks</option>
                {bankAccounts.map((bank) => (
                  <option key={bank.id} value={bank.id}>
                    {bank.account_name} ({bank.provider})
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
                <option value="">All bank accounts</option>
                {qbBankAccounts.map((account) => (
                  <option key={account.qb_account_id} value={account.qb_account_id}>
                    {account.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm text-slate-400">
              Side
              <select
                value={transactionSide}
                onChange={(e) => setTransactionSide(e.target.value as ReconciliationSide)}
                className={selectClass}
              >
                <option value="debit">Debits (expenses)</option>
                <option value="credit">Credits (deposits)</option>
                <option value="all">All</option>
              </select>
            </label>
            <Button onClick={run} disabled={loading}>
              {loading ? <Spinner size="sm" className="mr-2" /> : <RefreshCw className="mr-2 h-4 w-4" />}
              Run
            </Button>
          </div>

          {missingBankMapping && (
            <p className="text-sm text-amber-400">
              This bank is not mapped to QuickBooks yet.{" "}
              <Link href="/books/mappings" className="underline hover:text-amber-300">
                Set up bank mapping
              </Link>{" "}
              for tighter matching.
            </p>
          )}
        </div>
      </Card>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {summary && (
        <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3 text-sm text-slate-300">
          <p>
            {summary.matched_count} of {summary.matched_count + summary.unmatched_bank_count} bank {sideLabel}{" "}
            matched ({(summary.match_rate * 100).toFixed(1)}%). Variance:{" "}
            {formatCurrency(summary.variance, "NGN")}
          </p>
          {(summary.filters?.bank_account_name || summary.filters?.qb_bank_account_name) && (
            <p className="mt-1 text-slate-500">
              {summary.filters.bank_account_name && <>Bank: {summary.filters.bank_account_name}</>}
              {summary.filters.bank_account_name && summary.filters.qb_bank_account_name && " · "}
              {summary.filters.qb_bank_account_name && <>QB: {summary.filters.qb_bank_account_name}</>}
            </p>
          )}
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

          <div className="overflow-hidden rounded-xl border border-slate-800">
            <table className="table-fit text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-left text-slate-500">
                  <th className="p-3">Date</th>
                  {!bankAccountId && <th className="p-3">Bank</th>}
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
                      account_name?: string;
                    };
                    return (
                      <tr key={i} className="border-b border-slate-800/50">
                        <td className="p-3">{bank.transaction_date}</td>
                        {!bankAccountId && <td className="p-3 text-slate-500">{bank.account_name ?? "—"}</td>}
                        <td className="p-3">{bank.merchant_name}</td>
                        <td className="p-3 text-right">
                          {formatCurrency(bank.amount ?? 0, bank.currency ?? "NGN")}
                        </td>
                        <td className="p-3 text-emerald-400">
                          Matched ({m.qb_kind === "deposit" ? "deposit" : "purchase"})
                        </td>
                      </tr>
                    );
                  })}
                {tab === "unmatched_bank" &&
                  result.unmatched_bank.map((b) => (
                    <tr key={String(b.id)} className="border-b border-slate-800/50">
                      <td className="p-3">{String(b.transaction_date)}</td>
                      {!bankAccountId && (
                        <td className="p-3 text-slate-500">{String(b.account_name || "—")}</td>
                      )}
                      <td className="p-3">{String(b.merchant_name || b.description || "—")}</td>
                      <td className="p-3 text-right">
                        {formatCurrency(Number(b.amount) || 0, String(b.currency || "NGN"))}
                      </td>
                      <td className="p-3">
                        <Link href="/books?status=pending">
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
                      {!bankAccountId && <td className="p-3 text-slate-500">—</td>}
                      <td className="p-3">
                        QBO {q.qb_kind === "deposit" ? "Deposit" : "Purchase"} #{String(q.Id || "—")}
                      </td>
                      <td className="p-3 text-right">{formatCurrency(Number(q.TotalAmt) || 0, "NGN")}</td>
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
