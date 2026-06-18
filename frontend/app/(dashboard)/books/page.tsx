"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertCircle, BookOpen, RefreshCw } from "lucide-react";
import { QuickBooksConnectButton } from "@/components/accounts/quickbooks-connect-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { Skeleton } from "@/components/ui/skeleton";
import {
  classifyTransactions,
  excludeTransaction,
  getBooksQueue,
  getBooksSummary,
  getQuickBooksStatus,
  listCoa,
  postTransaction,
  postTransactionsBulk,
  syncCoa,
  type QbSyncStatus,
  type QueueItem,
} from "@/lib/books";
import { ApiError } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";

const STATUS_TABS: { id: QbSyncStatus | "all"; label: string }[] = [
  { id: "pending", label: "Pending" },
  { id: "needs_review", label: "Needs review" },
  { id: "posted", label: "Posted" },
  { id: "excluded", label: "Excluded" },
  { id: "failed", label: "Failed" },
];

function confidenceBadge(confidence: number | null | undefined) {
  if (confidence == null) return <Badge variant="secondary">—</Badge>;
  if (confidence >= 0.92) return <Badge className="bg-emerald-600/20 text-emerald-400">High</Badge>;
  if (confidence >= 0.85) return <Badge className="bg-amber-600/20 text-amber-400">Medium</Badge>;
  return <Badge className="bg-red-600/20 text-red-400">Low</Badge>;
}

function BooksQueueContent() {
  const searchParams = useSearchParams();
  const status = (searchParams.get("status") as QbSyncStatus) || "pending";
  const page = Number(searchParams.get("page") || "1");

  const [qbConnected, setQbConnected] = useState<boolean | null>(null);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [totalPages, setTotalPages] = useState(1);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qb = await getQuickBooksStatus();
      setQbConnected(qb.connected);
      if (!qb.connected) return;

      const coa = await listCoa();
      if (coa.total === 0) {
        await syncCoa();
      }
      await classifyTransactions();
      const [queue, sum] = await Promise.all([
        getBooksQueue(status, page, 20),
        getBooksSummary(),
      ]);
      setItems(queue.items);
      setTotalPages(queue.total_pages);
      setSummary(sum.counts);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load books queue");
    } finally {
      setLoading(false);
    }
  }, [status, page]);

  useEffect(() => {
    load();
  }, [load]);

  async function handlePost(id: string) {
    setActionLoading(id);
    setError(null);
    try {
      await postTransaction(id);
      setInfo("Transaction posted to QuickBooks");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Post failed");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleBulkPost() {
    if (selected.size === 0) return;
    setActionLoading("bulk");
    setError(null);
    try {
      const result = await postTransactionsBulk([...selected]);
      setInfo(`Posted ${result.posted}, skipped ${result.skipped}, failed ${result.failed}`);
      setSelected(new Set());
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Bulk post failed");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleExclude(id: string) {
    setActionLoading(id);
    try {
      await excludeTransaction(id);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Exclude failed");
    } finally {
      setActionLoading(null);
    }
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  if (qbConnected === null || loading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (!qbConnected) {
    return (
      <Card className="border-slate-800 bg-slate-900/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <BookOpen className="h-5 w-5 text-blue-500" />
            Connect QuickBooks
          </CardTitle>
        </CardHeader>
        <div className="space-y-4">
          <p className="text-sm text-slate-400">
            Connect QuickBooks to classify bank transactions and post expenses directly to your ledger —
            bypassing the manual For Review queue.
          </p>
          <QuickBooksConnectButton />
          <p className="text-xs text-slate-500">
            Or go to <Link href="/accounts" className="text-blue-400 hover:underline">Accounts</Link> to
            manage connections.
          </p>
        </div>
      </Card>
    );
  }

  return (
    <div className="page-enter space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Books Queue</h1>
        <p className="text-slate-400">
          Review and post bank transactions to QuickBooks. Disable QBO bank feeds for accounts synced via
          Plaid to avoid duplicates.
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          {error}
        </div>
      )}
      {info && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">
          {info}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {STATUS_TABS.map((tab) => {
          const count = summary[tab.id] ?? 0;
          const active = status === tab.id;
          return (
            <Link
              key={tab.id}
              href={`/books?status=${tab.id}`}
              className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
                active
                  ? "bg-blue-600/20 text-blue-400 ring-1 ring-blue-500/30"
                  : "bg-slate-800/50 text-slate-400 hover:text-white"
              }`}
            >
              {tab.label}
              {count > 0 && <span className="ml-1.5 text-xs opacity-70">({count})</span>}
            </Link>
          );
        })}
        <Button variant="ghost" size="sm" onClick={() => load()} className="ml-auto text-slate-400">
          <RefreshCw className="mr-1 h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      {(status === "pending" || status === "needs_review") && selected.size > 0 && (
        <Button onClick={handleBulkPost} disabled={actionLoading === "bulk"}>
          {actionLoading === "bulk" ? <Spinner size="sm" className="mr-2" /> : null}
          Post {selected.size} selected
        </Button>
      )}

      <div className="overflow-x-auto rounded-xl border border-slate-800/70">
        <table className="w-full min-w-[800px] text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-left text-slate-500">
              {(status === "pending" || status === "needs_review") && (
                <th className="p-3 w-8">
                  <span className="sr-only">Select</span>
                </th>
              )}
              <th className="p-3">Date</th>
              <th className="p-3">Merchant</th>
              <th className="p-3">Category</th>
              <th className="p-3">QB Account</th>
              <th className="p-3">Confidence</th>
              <th className="p-3 text-right">Amount</th>
              <th className="p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td colSpan={8} className="p-8 text-center text-slate-500">
                  No transactions in this queue.{" "}
                  <Link href="/books/mappings" className="text-blue-400 hover:underline">
                    Configure mappings
                  </Link>{" "}
                  or sync bank transactions first.
                </td>
              </tr>
            ) : (
              items.map((row) => (
                <tr key={row.id} className="border-b border-slate-800/50 hover:bg-slate-900/40">
                  {(status === "pending" || status === "needs_review") && (
                    <td className="p-3">
                      <input
                        type="checkbox"
                        checked={selected.has(row.id)}
                        onChange={() => toggleSelect(row.id)}
                        className="rounded border-slate-600"
                      />
                    </td>
                  )}
                  <td className="p-3 text-slate-300">{row.transaction_date}</td>
                  <td className="p-3 text-white">
                    {row.merchant_name || row.description || "—"}
                    {row.account_name && (
                      <span className="block text-xs text-slate-500">{row.account_name}</span>
                    )}
                  </td>
                  <td className="p-3 text-slate-400">{row.category || "—"}</td>
                  <td className="p-3 text-slate-300">{row.qb_account_name || row.qb_account_id || "—"}</td>
                  <td className="p-3">{confidenceBadge(row.qb_confidence)}</td>
                  <td className="p-3 text-right font-medium text-white">
                    {formatCurrency(row.amount, row.currency)}
                  </td>
                  <td className="p-3">
                    <div className="flex gap-2">
                      {(status === "pending" || status === "needs_review" || status === "failed") && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={actionLoading === row.id}
                          onClick={() => handlePost(row.id)}
                        >
                          {actionLoading === row.id ? <Spinner size="sm" /> : "Post"}
                        </Button>
                      )}
                      {status !== "posted" && status !== "excluded" && (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={actionLoading === row.id}
                          onClick={() => handleExclude(row.id)}
                        >
                          Exclude
                        </Button>
                      )}
                      {row.qb_error && (
                        <span className="text-xs text-red-400" title={row.qb_error}>
                          Error
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex justify-center gap-2">
          {page > 1 && (
            <Link href={`/books?status=${status}&page=${page - 1}`}>
              <Button variant="outline" size="sm">
                Previous
              </Button>
            </Link>
          )}
          <span className="flex items-center px-3 text-sm text-slate-500">
            Page {page} of {totalPages}
          </span>
          {page < totalPages && (
            <Link href={`/books?status=${status}&page=${page + 1}`}>
              <Button variant="outline" size="sm">
                Next
              </Button>
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

export default function BooksPage() {
  return (
    <Suspense fallback={<Skeleton className="h-48 w-full" />}>
      <BooksQueueContent />
    </Suspense>
  );
}
