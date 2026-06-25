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
  approveBulk,
  approveTransaction,
  classifyTransactions,
  excludeTransaction,
  getAutomationSettings,
  getBooksGroups,
  getBooksQueue,
  getBooksSummary,
  getQuickBooksStatus,
  listCoa,
  postTransaction,
  postTransactionsBulk,
  setPostingIntent,
  syncCoa,
  type AutomationSettings,
  type CoaAccount,
  type QbSyncStatus,
  type QueueGroup,
  type QueueItem,
} from "@/lib/books";
import { ApiError } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";

const STATUS_TABS: { id: QbSyncStatus; label: string }[] = [
  { id: "pending", label: "Pending" },
  { id: "needs_review", label: "Needs review" },
  { id: "auto_approved", label: "Auto-approved" },
  { id: "posted", label: "Posted" },
  { id: "excluded", label: "Excluded" },
  { id: "failed", label: "Failed" },
];

const selectClass =
  "h-9 min-w-[160px] rounded-md border border-slate-700 bg-slate-900 px-2 text-sm text-white";

function confidenceBadge(confidence: number | null | undefined) {
  if (confidence == null) return <Badge variant="secondary">—</Badge>;
  if (confidence >= 0.9) return <Badge className="bg-emerald-600/20 text-emerald-400">High</Badge>;
  if (confidence >= 0.6) return <Badge className="bg-amber-600/20 text-amber-400">Medium</Badge>;
  return <Badge className="bg-red-600/20 text-red-400">Low</Badge>;
}

function methodLabel(method: string | null | undefined) {
  if (!method) return null;
  const labels: Record<string, string> = {
    rule: "Rule",
    fingerprint: "Fingerprint",
    rag: "RAG",
    llm: "AI",
    auto: "Auto",
    manual: "Manual",
  };
  return labels[method] ?? method;
}

function BooksQueueContent() {
  const searchParams = useSearchParams();
  const status = (searchParams.get("status") as QbSyncStatus) || "pending";
  const page = Number(searchParams.get("page") || "1");
  const view = searchParams.get("view") || "list";

  const [qbConnected, setQbConnected] = useState<boolean | null>(null);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [groups, setGroups] = useState<QueueGroup[]>([]);
  const [expenseCoa, setExpenseCoa] = useState<CoaAccount[]>([]);
  const [accountEdits, setAccountEdits] = useState<Record<string, string>>({});
  const [totalPages, setTotalPages] = useState(1);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [automation, setAutomation] = useState<AutomationSettings | null>(null);
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
      if (coa.total === 0) await syncCoa();
      const expense = await listCoa("Expense");
      setExpenseCoa(expense.items);

      await classifyTransactions();
      const [queue, sum, auto, grp] = await Promise.all([
        getBooksQueue(status, page, 20),
        getBooksSummary(),
        getAutomationSettings(),
        view === "grouped" && (status === "pending" || status === "needs_review")
          ? getBooksGroups(status)
          : Promise.resolve([]),
      ]);
      setItems(queue.items);
      setTotalPages(queue.total_pages);
      setSummary(sum.counts);
      setAutomation(sum.automation ?? auto);
      setGroups(grp);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load books queue");
    } finally {
      setLoading(false);
    }
  }, [status, page, view]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleApprove(row: QueueItem, post = true) {
    const accountId = accountEdits[row.id] || row.qb_account_id;
    if (!accountId) {
      setError("Select a QuickBooks expense account first");
      return;
    }
    setActionLoading(row.id);
    setError(null);
    try {
      await approveTransaction(row.id, accountId, post);
      setInfo(post ? "Approved and posted to QuickBooks" : "Approved — training saved");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Approve failed");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleGroupApprove(group: QueueGroup) {
    if (!group.qb_account_id) {
      setError("No suggested account for this group");
      return;
    }
    setActionLoading(`group-${group.payee_pattern}`);
    try {
      const result = await approveBulk({
        payee_pattern: group.payee_pattern,
        final_account_id: group.qb_account_id,
        post: true,
      });
      setInfo(`Approved ${result.approved} transactions in group`);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Group approve failed");
    } finally {
      setActionLoading(null);
    }
  }

  async function handlePost(id: string) {
    setActionLoading(id);
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

  async function handleTeachExpense(id: string) {
    setActionLoading(id);
    try {
      await setPostingIntent(id, "expense");
      setInfo("Marked as expense — re-classifying");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Intent update failed");
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
        <div className="space-y-4 px-6 pb-6">
          <p className="text-sm text-slate-400">
            Connect QuickBooks to approve bank transactions and post expenses with AI-assisted learning.
          </p>
          <QuickBooksConnectButton />
        </div>
      </Card>
    );
  }

  return (
    <div className="page-enter space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Books Queue</h1>
        <p className="text-slate-400">
          Approve transactions to train FinSight. High-confidence patterns can auto-post overnight.
        </p>
      </div>

      {automation && (
        <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3 text-sm text-slate-300">
          Auto-posting is{" "}
          <strong className={automation.auto_approve_enabled ? "text-emerald-400" : "text-amber-400"}>
            {automation.auto_approve_enabled ? "ON" : "OFF"}
          </strong>
          {automation.auto_approve_enabled && (
            <span> at {(automation.auto_approve_threshold * 100).toFixed(0)}% confidence</span>
          )}
          .{" "}
          <Link href="/settings" className="text-blue-400 hover:underline">
            Settings
          </Link>
        </div>
      )}

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

      <div className="flex flex-wrap items-center gap-2">
        {STATUS_TABS.map((tab) => {
          const count = summary[tab.id] ?? 0;
          const active = status === tab.id;
          return (
            <Link
              key={tab.id}
              href={`/books?status=${tab.id}&view=${view}`}
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
        <Link
          href={`/books?status=${status}&view=${view === "grouped" ? "list" : "grouped"}`}
          className="rounded-lg bg-slate-800/50 px-3 py-1.5 text-sm text-slate-400 hover:text-white"
        >
          {view === "grouped" ? "List view" : "Grouped by payee"}
        </Link>
        <Button variant="ghost" size="sm" onClick={() => load()} className="ml-auto text-slate-400">
          <RefreshCw className="mr-1 h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      {view === "grouped" && groups.length > 0 && (
        <div className="space-y-3">
          {groups.map((g) => (
            <div
              key={g.payee_pattern}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/40 p-4"
            >
              <div>
                <p className="font-medium text-white">{g.payee_pattern}</p>
                <p className="text-sm text-slate-400">
                  {g.count} transactions · {formatCurrency(g.total_amount, "NGN")} →{" "}
                  {g.qb_account_name || "—"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {confidenceBadge(g.qb_confidence)}
                <Button
                  size="sm"
                  disabled={actionLoading === `group-${g.payee_pattern}`}
                  onClick={() => handleGroupApprove(g)}
                >
                  Approve all
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {(status === "pending" || status === "needs_review") && selected.size > 0 && (
        <Button onClick={handleBulkPost} disabled={actionLoading === "bulk"}>
          Post {selected.size} selected
        </Button>
      )}

      <div className="overflow-x-auto rounded-xl border border-slate-800/70">
        <table className="w-full min-w-[960px] text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-left text-slate-500">
              {(status === "pending" || status === "needs_review") && (
                <th className="p-3 w-8">
                  <span className="sr-only">Select</span>
                </th>
              )}
              <th className="p-3">Date</th>
              <th className="p-3">Merchant</th>
              <th className="p-3">QB Account</th>
              <th className="p-3">Confidence</th>
              <th className="p-3">Method</th>
              <th className="p-3 text-right">Amount</th>
              <th className="p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td colSpan={9} className="p-8 text-center text-slate-500">
                  No transactions in this queue.{" "}
                  <Link href="/books/mappings" className="text-blue-400 hover:underline">
                    Configure mappings
                  </Link>
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
                    {row.payee_pattern && (
                      <span className="block text-xs text-slate-500">{row.payee_pattern}</span>
                    )}
                  </td>
                  <td className="p-3">
                    {(status === "pending" || status === "needs_review") && expenseCoa.length > 0 ? (
                      <select
                        className={selectClass}
                        value={accountEdits[row.id] ?? row.qb_account_id ?? ""}
                        onChange={(e) =>
                          setAccountEdits((prev) => ({ ...prev, [row.id]: e.target.value }))
                        }
                      >
                        <option value="">Select account…</option>
                        {expenseCoa.map((a) => (
                          <option key={a.qb_account_id} value={a.qb_account_id}>
                            {a.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="text-slate-300">{row.qb_account_name || "—"}</span>
                    )}
                  </td>
                  <td className="p-3" title={row.qb_confidence_reason ?? undefined}>
                    {confidenceBadge(row.qb_confidence)}
                  </td>
                  <td className="p-3 text-slate-400">{methodLabel(row.qb_suggestion_method) ?? "—"}</td>
                  <td className="p-3 text-right font-medium text-white">
                    {formatCurrency(row.amount, row.currency)}
                  </td>
                  <td className="p-3">
                    <div className="flex flex-wrap gap-2">
                      {(status === "pending" || status === "needs_review") && (
                        <>
                          <Button
                            size="sm"
                            disabled={actionLoading === row.id}
                            onClick={() => handleApprove(row, true)}
                          >
                            Approve & Post
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={actionLoading === row.id}
                            onClick={() => handleApprove(row, false)}
                          >
                            Approve
                          </Button>
                        </>
                      )}
                      {status === "failed" && (
                        <Button size="sm" variant="outline" onClick={() => handlePost(row.id)}>
                          Retry
                        </Button>
                      )}
                      {status === "excluded" && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleTeachExpense(row.id)}
                        >
                          Teach as expense
                        </Button>
                      )}
                      {status !== "posted" && status !== "excluded" && (
                        <Button size="sm" variant="ghost" onClick={() => handleExclude(row.id)}>
                          Exclude
                        </Button>
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
            <Link href={`/books?status=${status}&page=${page - 1}&view=${view}`}>
              <Button variant="outline" size="sm">
                Previous
              </Button>
            </Link>
          )}
          <span className="flex items-center px-3 text-sm text-slate-500">
            Page {page} of {totalPages}
          </span>
          {page < totalPages && (
            <Link href={`/books?status=${status}&page=${page + 1}&view=${view}`}>
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
