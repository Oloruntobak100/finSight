"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertCircle, BookOpen, RefreshCw } from "lucide-react";
import { QuickBooksConnectButton } from "@/components/accounts/quickbooks-connect-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
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
  type BooksReadiness,
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
  { id: "excluded", label: "Transfers" },
  { id: "failed", label: "Failed" },
];

function postingTypeLabel(type: string | null | undefined, txnType?: string) {
  if (type === "deposit") return "Income";
  if (type === "fee") return "Fee";
  if (type === "transfer") return "Transfer";
  if (type === "expense") return "Expense";
  if (txnType === "credit") return "Income";
  return "—";
}

function coaForRow(
  row: QueueItem,
  expenseCoa: CoaAccount[],
  incomeCoa: CoaAccount[]
): CoaAccount[] {
  if (row.qb_posting_type === "deposit" || row.transaction_type === "credit") {
    return incomeCoa;
  }
  return expenseCoa;
}

const selectClass =
  "h-9 min-w-[160px] rounded-md border border-slate-700 bg-slate-900 px-2 text-sm text-white";

function confidenceBadge(
  confidence: number | null | undefined,
  syncStatus?: QbSyncStatus | null
) {
  if (syncStatus === "excluded") {
    return (
      <Badge className="bg-slate-600/20 text-slate-300" title="Detected as a bank transfer">
        Transfer
      </Badge>
    );
  }
  if (syncStatus === "skipped") {
    return (
      <Badge className="bg-slate-600/20 text-slate-300" title="Not an expense transaction">
        Skipped
      </Badge>
    );
  }
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
  const [qbEnvironment, setQbEnvironment] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<BooksReadiness | null>(null);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [groups, setGroups] = useState<QueueGroup[]>([]);
  const [expenseCoa, setExpenseCoa] = useState<CoaAccount[]>([]);
  const [incomeCoa, setIncomeCoa] = useState<CoaAccount[]>([]);
  const [accountEdits, setAccountEdits] = useState<Record<string, string>>({});
  const [totalPages, setTotalPages] = useState(1);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [automation, setAutomation] = useState<AutomationSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [classifying, setClassifying] = useState(false);

  const refreshQueue = useCallback(
    async (statusFilter: QbSyncStatus, pageNum: number, viewMode: string) => {
      const [queue, sum, grp] = await Promise.all([
        getBooksQueue(statusFilter, pageNum, 20),
        getBooksSummary(),
        viewMode === "grouped" && (statusFilter === "pending" || statusFilter === "needs_review")
          ? getBooksGroups(statusFilter)
          : Promise.resolve([]),
      ]);
      setItems(queue.items);
      setTotalPages(queue.total_pages);
      setSummary(sum.counts);
      setReadiness(sum.readiness ?? null);
      setGroups(grp);
    },
    []
  );

  const runBackgroundClassify = useCallback(async () => {
    setClassifying(true);
    try {
      await classifyTransactions();
      await refreshQueue(status, page, view);
    } catch {
      /* non-blocking — queue already visible */
    } finally {
      setClassifying(false);
    }
  }, [status, page, view, refreshQueue]);

  const load = useCallback(
    async (opts?: { classify?: boolean }) => {
      setLoading(true);
      setError(null);
      try {
        const qb = await getQuickBooksStatus();
        setQbConnected(qb.connected);
        setQbEnvironment(qb.environment ?? null);
        if (!qb.connected) return;

        const sum = await getBooksSummary();
        setReadiness(sum.readiness ?? null);
        setSummary(sum.counts);
        setAutomation(sum.automation ?? null);

        if (!sum.readiness?.bank_connected) {
          return;
        }

        const [coa, expense, income, auto] = await Promise.all([
          listCoa(),
          listCoa("Expense"),
          listCoa("Income"),
          getAutomationSettings(),
        ]);
        if (coa.total === 0) await syncCoa();
        setExpenseCoa(expense.items);
        setIncomeCoa(income.items);
        if (!sum.automation) setAutomation(auto);

        await refreshQueue(status, page, view);

        if (opts?.classify) {
          setClassifying(true);
          try {
            await classifyTransactions();
            await refreshQueue(status, page, view);
          } finally {
            setClassifying(false);
          }
        } else {
          void runBackgroundClassify();
        }
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Failed to load books queue");
      } finally {
        setLoading(false);
      }
    },
    [status, page, view, refreshQueue, runBackgroundClassify]
  );

  useEffect(() => {
    load();
  }, [load]);

  async function handleApprove(row: QueueItem, post = true) {
    const accountId = accountEdits[row.id] || row.qb_account_id;
    if (!accountId) {
      setError("Select a QuickBooks account first");
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

  async function handleTeachIntent(id: string, intent: "expense" | "income") {
    setActionLoading(id);
    try {
      await setPostingIntent(id, intent);
      setInfo(`Marked as ${intent} — re-classifying`);
      await load({ classify: true });
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
            Connect QuickBooks to approve bank transactions and post expenses, income, and fees with AI-assisted learning.
          </p>
          <QuickBooksConnectButton />
        </div>
      </Card>
    );
  }

  if (readiness && !readiness.bank_connected) {
    return (
      <div className="page-enter space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Books Queue</h1>
          <p className="text-slate-400">Connect a bank to sync transactions for posting to QuickBooks.</p>
        </div>

        {qbEnvironment === "sandbox" && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-950/20 px-4 py-3 text-sm text-amber-200">
            QuickBooks is connected as a <strong>sandbox test company</strong> — fine for testing, not your live books.
          </div>
        )}

        <Card className="border-slate-800 bg-slate-900/50">
          <CardHeader>
            <CardTitle className="text-lg">No bank account connected</CardTitle>
          </CardHeader>
          <div className="space-y-4 px-6 pb-6">
            <p className="text-sm text-slate-400">
              Books shows transactions from your linked bank only. Connect Mono or Plaid to import live debits, then map
              accounts and approve for QuickBooks.
            </p>
            <Button asChild>
              <Link href="/accounts">Connect a bank account</Link>
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="page-enter space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Books Queue</h1>
        <p className="text-slate-400">
          Review all bank debits and credits. Train FinSight to map each line to QuickBooks — expenses,
          income, fees, or transfers.
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
        <Button
          variant="ghost"
          size="sm"
          onClick={() => load({ classify: true })}
          loading={classifying}
          loadingLabel="Classifying…"
          className="ml-auto text-slate-400"
        >
          <RefreshCw className="mr-1 h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      {classifying && (
        <div className="rounded-lg border border-blue-500/20 bg-blue-950/20 px-4 py-2 text-sm text-blue-200">
          Classifying transactions (rules → fingerprints → similar approvals → AI)…
        </div>
      )}

      <p className="text-xs text-slate-500">
        Classification order: mapping rules → learned fingerprints → similar past approvals (RAG) → AI.
        Use Refresh to re-run on unmapped lines. Transfers holds NIP-style movements — teach as expense or
        income if misclassified.
      </p>

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
                {confidenceBadge(g.qb_confidence, status)}
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
              <th className="p-3">Type</th>
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
                <td colSpan={10} className="p-8 text-center text-slate-500">
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
                    <span
                      className={`rounded px-2 py-0.5 text-xs ${
                        row.qb_posting_type === "deposit" || row.transaction_type === "credit"
                          ? "bg-emerald-900/40 text-emerald-300"
                          : row.qb_posting_type === "fee"
                            ? "bg-amber-900/40 text-amber-300"
                            : row.qb_posting_type === "transfer" || row.qb_sync_status === "excluded"
                              ? "bg-slate-800 text-slate-400"
                              : "bg-blue-900/40 text-blue-300"
                      }`}
                    >
                      {postingTypeLabel(row.qb_posting_type, row.transaction_type)}
                    </span>
                  </td>
                  <td className="p-3">
                    {(status === "pending" || status === "needs_review") &&
                    coaForRow(row, expenseCoa, incomeCoa).length > 0 ? (
                      <select
                        className={selectClass}
                        value={accountEdits[row.id] ?? row.qb_account_id ?? ""}
                        onChange={(e) =>
                          setAccountEdits((prev) => ({ ...prev, [row.id]: e.target.value }))
                        }
                      >
                        <option value="">Select account…</option>
                        {coaForRow(row, expenseCoa, incomeCoa).map((a) => (
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
                    {confidenceBadge(row.qb_confidence, row.qb_sync_status)}
                  </td>
                  <td className="p-3 text-slate-400">
                    {row.qb_sync_status === "excluded"
                      ? "Transfer"
                      : methodLabel(row.qb_suggestion_method) ?? "—"}
                  </td>
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
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={actionLoading === row.id}
                            onClick={() => handleTeachIntent(row.id, "expense")}
                          >
                            Teach as expense
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={actionLoading === row.id}
                            onClick={() => handleTeachIntent(row.id, "income")}
                          >
                            Teach as income
                          </Button>
                        </>
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
