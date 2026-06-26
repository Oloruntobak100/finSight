"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertCircle, BookOpen, RefreshCw } from "lucide-react";
import { QuickBooksConnectButton } from "@/components/accounts/quickbooks-connect-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { PageLoader } from "@/components/ui/page-loader";
import {
  approveBulk,
  approveTransaction,
  classifyTransactions,
  getAutomationSettings,
  getBooksGroups,
  getBooksQueue,
  getBooksSummary,
  getQuickBooksStatus,
  listCoa,
  postTransaction,
  postTransactionsBulk,
  revertTransaction,
  setPostingIntent,
  syncCoa,
  type AutomationSettings,
  type BooksReadiness,
  type CoaAccount,
  type QbSyncStatus,
  type QueueGroup,
  type QueueItem,
  type RevertTarget,
} from "@/lib/books";
import { ApiError } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";

const STATUS_TABS: { id: QbSyncStatus; label: string }[] = [
  { id: "unclassified", label: "New" },
  { id: "pending", label: "Pending" },
  { id: "needs_review", label: "Review" },
  { id: "auto_approved", label: "Auto" },
  { id: "posted", label: "Posted" },
  { id: "excluded", label: "All transactions" },
  { id: "failed", label: "Failed" },
];

function postingTypeLabel(
  type: string | null | undefined,
  txnType?: string,
  reason?: string | null
) {
  if (type === "refund") return "Refund";
  if (type === "deposit") return "Income";
  if (type === "fee") return "Fee";
  if (type === "transfer") return "Transfer";
  if (type === "expense") return "Expense";
  if (type === "skip" && reason?.toLowerCase().includes("balance sheet")) return "Balance sheet";
  if (txnType === "credit") return "Income";
  return "—";
}

function coaForRow(
  row: QueueItem,
  expenseCoa: CoaAccount[],
  incomeCoa: CoaAccount[]
): CoaAccount[] {
  if (row.qb_posting_type === "deposit") {
    return incomeCoa;
  }
  if (
    row.qb_posting_type === "refund" ||
    row.qb_posting_type === "expense" ||
    row.qb_posting_type === "fee"
  ) {
    return expenseCoa;
  }
  if (row.transaction_type === "credit") {
    return incomeCoa;
  }
  return expenseCoa;
}

const selectClass =
  "h-8 w-full max-w-full rounded-md border border-slate-700 bg-slate-900 px-1.5 text-xs text-white";

function confidenceBadge(
  confidence: number | null | undefined,
  syncStatus?: QbSyncStatus | null,
  reason?: string | null
) {
  if (syncStatus === "excluded" || syncStatus === "unclassified") {
    return (
      <Badge className="bg-slate-600/20 text-slate-300" title={reason ?? undefined}>
        —
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

function directionLabel(row: QueueItem) {
  const cat = (row.category || "").trim();
  if (/transfer in/i.test(cat)) return "Transfer In";
  if (/transfer out/i.test(cat)) return "Transfer Out";
  return row.transaction_type === "credit" ? "Credit" : "Debit";
}

function signedAmount(row: QueueItem) {
  const incoming = row.transaction_type === "credit";
  return `${incoming ? "+" : "-"}${formatCurrency(row.amount, row.currency)}`;
}

function kindLabel(row: QueueItem) {
  const type = postingTypeLabel(row.qb_posting_type, row.transaction_type, row.qb_confidence_reason);
  const direction = directionLabel(row);
  return { type, direction, title: `${direction} · ${type}` };
}

function matchLabel(
  confidence: number | null | undefined,
  syncStatus?: QbSyncStatus | null,
  method?: string | null,
  reason?: string | null
) {
  const methodText = methodLabel(method);
  const title = [reason, methodText].filter(Boolean).join(" · ") || undefined;
  if (syncStatus === "excluded" || syncStatus === "unclassified") {
    return { badge: confidenceBadge(confidence, syncStatus, reason), sub: null, title };
  }
  return {
    badge: confidenceBadge(confidence, syncStatus, reason),
    sub: methodText,
    title,
  };
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
    auto_detect: "Auto-detect",
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
  const [coverage, setCoverage] = useState<{ total_bank_transactions: number; classified: number; unclassified: number } | null>(null);
  const [queueTotal, setQueueTotal] = useState(0);
  const [classifyProgress, setClassifyProgress] = useState<string | null>(null);
  const [automation, setAutomation] = useState<AutomationSettings | null>(null);
  const [bootstrapped, setBootstrapped] = useState(false);
  const [loading, setLoading] = useState(true);
  const [queueLoading, setQueueLoading] = useState(false);
  const skipQueueRefresh = useRef(true);
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
      setQueueTotal(queue.total);
      setSummary(sum.counts);
      setCoverage(sum.coverage ?? null);
      setReadiness(sum.readiness ?? null);
      setGroups(grp);
    },
    []
  );

  const runClassifyAll = useCallback(async () => {
    setClassifying(true);
    setClassifyProgress(null);
    try {
      let remaining = 1;
      let total = 0;
      while (remaining > 0) {
        const result = await classifyTransactions();
        total += result.classified;
        remaining = result.remaining_unclassified;
        const sum = await getBooksSummary();
        setCoverage(sum.coverage ?? null);
        setSummary(sum.counts);
        setClassifyProgress(
          remaining > 0
            ? `Classified ${total}… ${remaining} remaining`
            : `Classified ${total} transaction(s)`
        );
        if (result.classified === 0) break;
      }
      await refreshQueue(status, page, view);
    } catch {
      /* non-blocking */
    } finally {
      setClassifying(false);
      setClassifyProgress(null);
    }
  }, [status, page, view, refreshQueue]);

  const refreshData = useCallback(
    async (opts?: { classify?: boolean }) => {
      setError(null);
      try {
        if (opts?.classify) {
          await runClassifyAll();
          return;
        }
        const sum = await getBooksSummary();
        setReadiness(sum.readiness ?? null);
        setSummary(sum.counts);
        setCoverage(sum.coverage ?? null);
        if (sum.automation) setAutomation(sum.automation);
        await refreshQueue(status, page, view);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Failed to refresh books queue");
      }
    },
    [status, page, view, refreshQueue, runClassifyAll]
  );

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      setLoading(true);
      setError(null);
      try {
        const qb = await getQuickBooksStatus();
        if (cancelled) return;
        setQbConnected(qb.connected);
        setQbEnvironment(qb.environment ?? null);
        if (!qb.connected) return;

        const sum = await getBooksSummary();
        if (cancelled) return;
        setReadiness(sum.readiness ?? null);
        setSummary(sum.counts);
        setCoverage(sum.coverage ?? null);
        setAutomation(sum.automation ?? null);

        if (!sum.readiness?.bank_connected) return;

        const needsGroups =
          view === "grouped" && (status === "pending" || status === "needs_review");

        const [coa, expense, income, auto, queue, grp] = await Promise.all([
          listCoa(),
          listCoa("Expense"),
          listCoa("Income"),
          sum.automation ? Promise.resolve(null) : getAutomationSettings(),
          getBooksQueue(status, page, 20),
          needsGroups ? getBooksGroups(status) : Promise.resolve([] as QueueGroup[]),
        ]);
        if (cancelled) return;

        if (coa.total === 0) await syncCoa();
        if (cancelled) return;

        setExpenseCoa(expense.items);
        setIncomeCoa(income.items);
        if (auto) setAutomation(auto);
        setItems(queue.items);
        setTotalPages(queue.total_pages);
        setQueueTotal(queue.total);
        setGroups(grp);
        setBootstrapped(true);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : "Failed to load books queue");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
    // Bootstrap once on mount; queue filters are applied via the initial searchParams snapshot above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!bootstrapped || !qbConnected) return;
    if (skipQueueRefresh.current) {
      skipQueueRefresh.current = false;
      return;
    }

    let cancelled = false;
    async function loadQueue() {
      setQueueLoading(true);
      try {
        await refreshQueue(status, page, view);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : "Failed to load queue");
        }
      } finally {
        if (!cancelled) setQueueLoading(false);
      }
    }

    void loadQueue();
    return () => {
      cancelled = true;
    };
  }, [status, page, view, bootstrapped, qbConnected, refreshQueue]);

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
      await refreshData();
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
      await refreshData();
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
      await refreshData();
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
      await refreshData();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Bulk post failed");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleRevert(id: string, target: RevertTarget) {
    setActionLoading(id);
    setError(null);
    const labels: Record<RevertTarget, string> = {
      excluded: "All transactions",
      needs_review: "Review",
      unclassified: "New",
    };
    try {
      await revertTransaction(id, target);
      setInfo(`Moved to ${labels[target]}`);
      await refreshData();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not move transaction");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleTeachIntent(id: string, intent: "expense" | "income") {
    setActionLoading(id);
    try {
      await setPostingIntent(id, intent);
      setInfo(`Marked as ${intent} — re-classifying`);
      await refreshData({ classify: true });
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
    return <PageLoader message="Loading books…" />;
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
    <div className="page-enter min-w-0 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-bold text-white md:text-2xl">Books Queue</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            {coverage && coverage.total_bank_transactions > 0 ? (
              <>
                {coverage.total_bank_transactions} transactions
                {coverage.unclassified > 0 ? (
                  <> · <span className="text-amber-400">{coverage.unclassified} unmapped</span></>
                ) : (
                  <> · <span className="text-emerald-400">all mapped</span></>
                )}
              </>
            ) : (
              "Map bank lines to QuickBooks"
            )}
            {automation && (
              <>
                {" · "}
                Auto-post{" "}
                <span className={automation.auto_approve_enabled ? "text-emerald-400" : "text-slate-400"}>
                  {automation.auto_approve_enabled ? "on" : "off"}
                </span>
              </>
            )}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => refreshData({ classify: true })}
          loading={classifying}
          loadingLabel="Classifying…"
          className="shrink-0 text-slate-300"
        >
          <RefreshCw className="mr-1 h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          {error}
        </div>
      )}
      {info && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
          {info}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1.5">
        {STATUS_TABS.map((tab) => {
          const count = summary[tab.id] ?? 0;
          const active = status === tab.id;
          return (
            <Link
              key={tab.id}
              href={`/books?status=${tab.id}&view=${view}`}
              className={`rounded-md px-2.5 py-1 text-xs transition-colors md:text-sm ${
                active
                  ? "bg-blue-600/20 text-blue-400 ring-1 ring-blue-500/30"
                  : "bg-slate-800/50 text-slate-400 hover:text-white"
              }`}
            >
              {tab.label}
              {count > 0 && <span className="ml-1 opacity-70">({count})</span>}
            </Link>
          );
        })}
        <Link
          href={`/books?status=${status}&view=${view === "grouped" ? "list" : "grouped"}`}
          className="rounded-md bg-slate-800/50 px-2.5 py-1 text-xs text-slate-400 hover:text-white md:text-sm"
        >
          {view === "grouped" ? "List" : "Grouped"}
        </Link>
      </div>

      {classifying && (
        <div className="rounded-lg border border-blue-500/20 bg-blue-950/20 px-3 py-2 text-sm text-blue-200">
          {classifyProgress ?? "Classifying…"}
        </div>
      )}

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

      <div className="relative overflow-hidden rounded-xl border border-slate-800/70">
        {queueLoading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-950/55 backdrop-blur-[1px]">
            <PageLoader variant="compact" message="" />
          </div>
        )}
        <table
          className={`table-fit text-sm transition-opacity ${queueLoading ? "pointer-events-none opacity-40" : ""}`}
        >
          <colgroup>
            {(status === "pending" || status === "needs_review") && <col className="w-8" />}
            <col className="w-[4.5rem]" />
            <col />
            <col className="w-[5.5rem]" />
            <col className="w-[22%]" />
            <col className="w-[4.5rem]" />
            <col className="w-[6.5rem]" />
            <col className="w-[5.5rem]" />
          </colgroup>
          <thead>
            <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
              {(status === "pending" || status === "needs_review") && (
                <th className="px-2 py-2">
                  <span className="sr-only">Select</span>
                </th>
              )}
              <th className="px-2 py-2">Date</th>
              <th className="px-2 py-2">Payee</th>
              <th className="px-2 py-2">Kind</th>
              <th className="px-2 py-2">Account</th>
              <th className="px-2 py-2">Match</th>
              <th className="px-2 py-2 text-right">Amount</th>
              <th className="px-2 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td
                  colSpan={status === "pending" || status === "needs_review" ? 8 : 7}
                  className="p-8 text-center text-slate-500"
                >
                  No transactions in this queue.{" "}
                  <Link href="/books/mappings" className="text-blue-400 hover:underline">
                    Mappings
                  </Link>
                </td>
              </tr>
            ) : (
              items.map((row) => {
                const kind = kindLabel(row);
                const match = matchLabel(
                  row.qb_confidence,
                  row.qb_sync_status,
                  row.qb_suggestion_method,
                  row.qb_confidence_reason
                );
                return (
                <tr key={row.id} className="border-b border-slate-800/50 hover:bg-slate-900/40">
                  {(status === "pending" || status === "needs_review") && (
                    <td className="px-2 py-2">
                      <input
                        type="checkbox"
                        checked={selected.has(row.id)}
                        onChange={() => toggleSelect(row.id)}
                        className="rounded border-slate-600"
                      />
                    </td>
                  )}
                  <td className="px-2 py-2 text-xs text-slate-400">{row.transaction_date.slice(5)}</td>
                  <td className="px-2 py-2 min-w-0">
                    <div className="cell-truncate font-medium text-white" title={row.merchant_name ?? undefined}>
                      {row.merchant_name || "—"}
                    </div>
                    <div
                      className="cell-truncate text-xs text-slate-500"
                      title={row.description ?? row.payee_pattern ?? undefined}
                    >
                      {row.description || row.payee_pattern || "—"}
                    </div>
                  </td>
                  <td className="px-2 py-2" title={kind.title}>
                    <span
                      className={`inline-block max-w-full truncate rounded px-1.5 py-0.5 text-[10px] ${
                        row.qb_posting_type === "deposit" ||
                        (row.transaction_type === "credit" &&
                          row.qb_posting_type !== "refund" &&
                          row.qb_sync_status !== "excluded")
                          ? "bg-emerald-900/40 text-emerald-300"
                          : row.qb_posting_type === "refund"
                            ? "bg-violet-900/40 text-violet-300"
                            : row.qb_posting_type === "fee"
                              ? "bg-amber-900/40 text-amber-300"
                              : row.qb_posting_type === "transfer" ||
                                  row.qb_sync_status === "excluded"
                                ? "bg-slate-800 text-slate-400"
                                : "bg-blue-900/40 text-blue-300"
                      }`}
                    >
                      {kind.type}
                    </span>
                  </td>
                  <td className="px-2 py-2 min-w-0">
                    {(status === "pending" || status === "needs_review") &&
                    coaForRow(row, expenseCoa, incomeCoa).length > 0 ? (
                      <select
                        className={selectClass}
                        value={accountEdits[row.id] ?? row.qb_account_id ?? ""}
                        onChange={(e) =>
                          setAccountEdits((prev) => ({ ...prev, [row.id]: e.target.value }))
                        }
                      >
                        <option value="">Select…</option>
                        {coaForRow(row, expenseCoa, incomeCoa).map((a) => (
                          <option key={a.qb_account_id} value={a.qb_account_id}>
                            {a.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="cell-truncate block text-slate-300" title={row.qb_account_name ?? undefined}>
                        {row.qb_account_name || "—"}
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2" title={match.title}>
                    <div className="flex flex-col gap-0.5">
                      {match.badge}
                      {match.sub && <span className="text-[10px] text-slate-500">{match.sub}</span>}
                    </div>
                  </td>
                  <td
                    className={`px-2 py-2 text-right text-xs font-medium tabular-nums ${
                      row.transaction_type === "credit" ? "text-green-400" : "text-white"
                    }`}
                  >
                    {signedAmount(row)}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex flex-wrap gap-1">
                      {(status === "pending" || status === "needs_review") && (
                        <>
                          <Button
                            size="sm"
                            className="h-7 px-2 text-xs"
                            disabled={actionLoading === row.id}
                            onClick={() => handleApprove(row, true)}
                          >
                            Post
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs"
                            disabled={actionLoading === row.id}
                            onClick={() => handleApprove(row, false)}
                          >
                            Save
                          </Button>
                        </>
                      )}
                      {status === "pending" && (
                        <>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-1.5 text-xs"
                            disabled={actionLoading === row.id}
                            onClick={() => handleRevert(row.id, "needs_review")}
                          >
                            Review
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-1.5 text-xs"
                            disabled={actionLoading === row.id}
                            onClick={() => handleRevert(row.id, "unclassified")}
                          >
                            New
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-1.5 text-xs"
                            disabled={actionLoading === row.id}
                            onClick={() => handleRevert(row.id, "excluded")}
                            title="Move to All transactions"
                          >
                            All
                          </Button>
                        </>
                      )}
                      {status === "needs_review" && (
                        <>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-1.5 text-xs"
                            disabled={actionLoading === row.id}
                            onClick={() => handleRevert(row.id, "excluded")}
                            title="Move to All transactions"
                          >
                            All
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-1.5 text-xs"
                            disabled={actionLoading === row.id}
                            onClick={() => handleRevert(row.id, "unclassified")}
                          >
                            New
                          </Button>
                        </>
                      )}
                      {status === "auto_approved" && (
                        <>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-1.5 text-xs"
                            disabled={actionLoading === row.id}
                            onClick={() => handleRevert(row.id, "needs_review")}
                          >
                            Review
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-1.5 text-xs"
                            disabled={actionLoading === row.id}
                            onClick={() => handleRevert(row.id, "excluded")}
                            title="Move to All transactions"
                          >
                            All
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-1.5 text-xs"
                            disabled={actionLoading === row.id}
                            onClick={() => handleRevert(row.id, "unclassified")}
                          >
                            New
                          </Button>
                        </>
                      )}
                      {status === "failed" && (
                        <>
                          <Button size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={() => handlePost(row.id)}>
                            Retry
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-1.5 text-xs"
                            disabled={actionLoading === row.id}
                            onClick={() => handleRevert(row.id, "needs_review")}
                          >
                            Review
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-1.5 text-xs"
                            disabled={actionLoading === row.id}
                            onClick={() => handleRevert(row.id, "unclassified")}
                          >
                            New
                          </Button>
                        </>
                      )}
                      {status === "excluded" && (
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs"
                            disabled={actionLoading === row.id}
                            onClick={() => handleTeachIntent(row.id, "expense")}
                          >
                            Expense
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs"
                            disabled={actionLoading === row.id}
                            onClick={() => handleTeachIntent(row.id, "income")}
                          >
                            Income
                          </Button>
                        </>
                      )}
                      {status === "unclassified" && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 px-2 text-xs"
                          disabled={actionLoading === row.id || classifying}
                          onClick={() => refreshData({ classify: true })}
                        >
                          Map
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              );
              })
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
            Showing {(page - 1) * 20 + 1}–{Math.min(page * 20, queueTotal)} of {queueTotal} · Page {page} of{" "}
            {totalPages}
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
    <Suspense fallback={<PageLoader message="Loading books…" />}>
      <BooksQueueContent />
    </Suspense>
  );
}
