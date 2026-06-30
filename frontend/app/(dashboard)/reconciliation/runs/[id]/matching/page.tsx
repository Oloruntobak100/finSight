"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { PageLoader } from "@/components/ui/page-loader";
import { TransactionDateStack } from "@/components/books/transaction-date-stack";
import { ApiError } from "@/lib/api";
import {
  getReconciliationRun,
  listReconciliationItems,
  MATCH_STATUS_LABELS,
  MONO_CLASSIFY_OPTIONS,
  QBO_CLASSIFY_OPTIONS,
  updateReconciliationItem,
  type ReconciliationItem,
  type ReconciliationRun,
} from "@/lib/reconciliation";
import { formatCurrency } from "@/lib/utils";
import { ReconciliationRunNav } from "../run-nav";

const selectClass =
  "rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white";

function itemPayee(item: ReconciliationItem): string {
  return item.payee || item.narration || "—";
}

function isPairedItem(item: ReconciliationItem): boolean {
  return (
    item.source === "BOTH" ||
    item.match_status === "SUGGESTED" ||
    item.match_status === "AMOUNT_MATCH_SUGGESTED" ||
    item.match_status === "AMBIGUOUS_MATCH" ||
    Boolean(item.mono_transaction_date && item.qbo_transaction_date)
  );
}

function MatchPairedCard({
  item,
  run,
  onConfirm,
  onReject,
  onClassify,
}: {
  item: ReconciliationItem;
  run: ReconciliationRun | null;
  onConfirm: () => void;
  onReject: () => void;
  onClassify: (status: string) => void;
}) {
  const monoDate = item.mono_transaction_date ?? item.transaction_date ?? "";
  const qboDate = item.qbo_transaction_date ?? item.transaction_date ?? "";
  const statusLabel = MATCH_STATUS_LABELS[item.match_status] ?? item.match_status;
  const needsConfirm =
    item.match_status === "SUGGESTED" ||
    item.match_status === "AMOUNT_MATCH_SUGGESTED" ||
    item.match_status === "AMBIGUOUS_MATCH";
  const locked = run?.status === "LOCKED";

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
          {statusLabel}
          {item.match_score ? (
            <span className="ml-1 normal-case text-slate-600">
              ({(item.match_score * 100).toFixed(0)}%)
            </span>
          ) : null}
        </span>
        {item.match_status === "MATCHED_EXACT" || item.match_status === "MATCHED_FUZZY" ? (
          <span className="text-xs text-emerald-400">✓ Matched</span>
        ) : null}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-slate-800/80 bg-slate-950/50 p-3">
          <p className="mb-2 text-[10px] font-medium uppercase tracking-wide text-slate-500">Bank (Mono)</p>
          <TransactionDateStack transactionDate={monoDate} unposted={!item.posted_date} />
          <p className="mt-2 text-lg font-semibold tabular-nums text-white">
            {formatCurrency(item.amount, item.currency)}
          </p>
          <p className="mt-1 truncate text-sm text-slate-300" title={itemPayee(item)}>
            {itemPayee(item)}
          </p>
        </div>
        <div className="rounded-lg border border-slate-800/80 bg-slate-950/50 p-3">
          <p className="mb-2 text-[10px] font-medium uppercase tracking-wide text-slate-500">Books (QBO)</p>
          <TransactionDateStack
            transactionDate={qboDate}
            postedDate={item.posted_date}
            postingLagDays={item.posting_lag_days}
          />
          <p className="mt-2 text-lg font-semibold tabular-nums text-white">
            {formatCurrency(item.amount, item.currency)}
          </p>
          <p className="mt-1 truncate text-sm text-slate-300" title={item.reference ?? undefined}>
            {item.reference || itemPayee(item)}
          </p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {needsConfirm && !locked && (
          <>
            <Button size="sm" onClick={onConfirm}>
              Confirm match
            </Button>
            <Button size="sm" variant="outline" onClick={onReject}>
              Reject
            </Button>
          </>
        )}
        {item.source === "MONO" && !needsConfirm && (
          <select
            className={selectClass}
            value={item.match_status}
            onChange={(e) => onClassify(e.target.value)}
            disabled={locked}
          >
            {MONO_CLASSIFY_OPTIONS.map((o) => (
              <option key={o} value={o}>
                {MATCH_STATUS_LABELS[o]}
              </option>
            ))}
          </select>
        )}
        {item.source === "QBO" && !needsConfirm && (
          <select
            className={selectClass}
            value={item.match_status}
            onChange={(e) => onClassify(e.target.value)}
            disabled={locked}
          >
            {QBO_CLASSIFY_OPTIONS.map((o) => (
              <option key={o} value={o}>
                {MATCH_STATUS_LABELS[o]}
              </option>
            ))}
          </select>
        )}
        {item.source === "MONO" && ["UNRECORDED_BANK_CHARGE", "UNEXPLAINED"].includes(item.match_status) && (
          <Link href="/books?status=pending" className="text-xs text-blue-400 underline">
            Books
          </Link>
        )}
      </div>
    </div>
  );
}

export default function MatchingWorkspacePage() {
  const params = useParams();
  const runId = String(params.id);
  const [run, setRun] = useState<ReconciliationRun | null>(null);
  const [items, setItems] = useState<ReconciliationItem[]>([]);
  const [filter, setFilter] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [r, list] = await Promise.all([
        getReconciliationRun(runId),
        listReconciliationItems(runId, filter ?? undefined),
      ]);
      setRun(r);
      setItems(list.items);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load matching workspace");
    } finally {
      setLoading(false);
    }
  }, [runId, filter]);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = run?.summary?.counts ?? {};
  const countChips = useMemo(() => Object.entries(counts).sort((a, b) => b[1] - a[1]), [counts]);

  async function classify(item: ReconciliationItem, match_status: string) {
    try {
      await updateReconciliationItem(runId, item.id, { match_status });
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Update failed");
    }
  }

  async function confirmSuggested(item: ReconciliationItem, accept: boolean) {
    try {
      await updateReconciliationItem(runId, item.id, {
        confirm_suggested: accept,
        reject_suggested: !accept,
      });
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Update failed");
    }
  }

  if (loading && !run) return <PageLoader message="Loading transaction matching…" />;

  const pairedItems = items.filter(isPairedItem);
  const soloItems = items.filter((i) => !isPairedItem(i));

  return (
    <div className="page-enter space-y-4">
      <ReconciliationRunNav runId={runId} status={run?.status} />

      <div>
        <h1 className="text-xl font-bold text-white">Transaction Matching</h1>
        <p className="text-sm text-slate-500">
          {run?.period_start} → {run?.period_end} · Mono vs QuickBooks bank register
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setFilter(null)}
          className={`rounded-lg px-3 py-1 text-sm ${!filter ? "bg-blue-600/20 text-blue-400" : "text-slate-400"}`}
        >
          All ({items.length})
        </button>
        {countChips.map(([status, n]) => (
          <button
            key={status}
            type="button"
            onClick={() => setFilter(status)}
            className={`rounded-lg px-3 py-1 text-sm ${filter === status ? "bg-blue-600/20 text-blue-400" : "text-slate-400"}`}
          >
            {MATCH_STATUS_LABELS[status] ?? status} ({n})
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {pairedItems.map((item) => (
          <MatchPairedCard
            key={item.id}
            item={item}
            run={run}
            onConfirm={() => void confirmSuggested(item, true)}
            onReject={() => void confirmSuggested(item, false)}
            onClassify={(status) => void classify(item, status)}
          />
        ))}
      </div>

      {soloItems.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-slate-800">
          <table className="table-fit w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-slate-500">
                <th className="p-3">Date</th>
                <th className="p-3">Payee</th>
                <th className="p-3">Source</th>
                <th className="p-3">Status</th>
                <th className="p-3 text-right">Amount</th>
                <th className="p-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {soloItems.map((item) => (
                <tr key={item.id} className="border-b border-slate-800/50">
                  <td className="p-3">
                    <TransactionDateStack
                      transactionDate={item.transaction_date ?? ""}
                      postedDate={item.posted_date}
                      postingLagDays={item.posting_lag_days}
                      unposted={item.source === "MONO" && !item.posted_date}
                    />
                  </td>
                  <td className="p-3 max-w-[12rem] truncate" title={itemPayee(item)}>
                    {itemPayee(item)}
                  </td>
                  <td className="p-3 text-slate-400">{item.source}</td>
                  <td className="p-3">
                    <span className="text-xs">{MATCH_STATUS_LABELS[item.match_status] ?? item.match_status}</span>
                  </td>
                  <td className="p-3 text-right">{formatCurrency(item.amount, item.currency)}</td>
                  <td className="p-3">
                    {item.match_status === "SUGGESTED" && (
                      <div className="flex gap-1">
                        <Button size="sm" variant="outline" onClick={() => void confirmSuggested(item, true)}>
                          Confirm
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => void confirmSuggested(item, false)}>
                          Reject
                        </Button>
                      </div>
                    )}
                    {item.source === "MONO" && item.match_status !== "SUGGESTED" && (
                      <select
                        className={selectClass}
                        value={item.match_status}
                        onChange={(e) => void classify(item, e.target.value)}
                        disabled={run?.status === "LOCKED"}
                      >
                        {MONO_CLASSIFY_OPTIONS.map((o) => (
                          <option key={o} value={o}>
                            {MATCH_STATUS_LABELS[o]}
                          </option>
                        ))}
                      </select>
                    )}
                    {item.source === "QBO" && item.match_status !== "SUGGESTED" && (
                      <select
                        className={selectClass}
                        value={item.match_status}
                        onChange={(e) => void classify(item, e.target.value)}
                        disabled={run?.status === "LOCKED"}
                      >
                        {QBO_CLASSIFY_OPTIONS.map((o) => (
                          <option key={o} value={o}>
                            {MATCH_STATUS_LABELS[o]}
                          </option>
                        ))}
                      </select>
                    )}
                    {item.source === "MONO" &&
                      ["UNRECORDED_BANK_CHARGE", "UNEXPLAINED"].includes(item.match_status) && (
                        <Link href="/books?status=pending" className="ml-2 text-xs text-blue-400 underline">
                          Books
                        </Link>
                      )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {items.length === 0 && !loading && (
        <p className="text-sm text-slate-500">No items in this filter.</p>
      )}

      <div className="flex justify-end">
        <Link href={`/reconciliation/runs/${runId}/balance-proof`}>
          <Button>Continue to Balance Proof →</Button>
        </Link>
      </div>
    </div>
  );
}
