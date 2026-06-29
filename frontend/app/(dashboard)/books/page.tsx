"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertCircle, BookOpen, ChevronDown, RefreshCw } from "lucide-react";
import { QuickBooksConnectButton } from "@/components/accounts/quickbooks-connect-button";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { PageLoader } from "@/components/ui/page-loader";
import { Spinner } from "@/components/ui/spinner";
import {
  approveBulk,
  approveTransaction,
  classifyTransactions,
  getAutomationSettings,
  getBooksQueue,
  getBooksSummary,
  getQuickBooksStatus,
  listCoa,
  postTransaction,
  revertTransaction,
  syncCoa,
  type AutomationSettings,
  type BooksReadiness,
  type CoaAccount,
  type QbSyncStatus,
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
];

const STATUS_TAB_HINTS: Partial<Record<QbSyncStatus, string>> = {
  unclassified:
    "Not categorized yet — not enough detail, or training has not started. Refresh or map manually.",
  needs_review:
    "Best guess from the transaction — pick QB accounts, select rows, then Save all or Post all.",
  pending:
    "Ready to post — select rows and Post all, or adjust accounts first.",
};

function kindLabel(row: QueueItem) {
  const postingType = row.qb_posting_type;
  const reason = row.qb_confidence_reason;
  const category = (row.category || "").trim();

  let type: string;
  if (postingType === "refund") {
    type = "Refund";
  } else if (postingType === "fee") {
    type = "Fee";
  } else if (postingType === "transfer") {
    type = "Transfer";
  } else if (postingType === "skip" && reason?.toLowerCase().includes("balance sheet")) {
    type = "Balance sheet";
  } else if (/transfer in/i.test(category)) {
    type = "Transfer In";
  } else if (/transfer out/i.test(category)) {
    type = "Transfer Out";
  } else {
    type = row.transaction_type === "credit" ? "Credit" : "Debit";
  }

  const direction = directionLabel(row);
  const title =
    type === "Credit" || type === "Debit"
      ? `${type} — map to the right QuickBooks account`
      : `${direction} · ${type}`;

  return { type, direction, title };
}

const POSTING_ACCOUNT_TYPES = new Set([
  "Income",
  "Expense",
  "Other Expense",
  "Cost of Goods Sold",
]);

function buildPostingCoa(accounts: CoaAccount[]): CoaAccount[] {
  return accounts
    .filter((a) => a.account_type && POSTING_ACCOUNT_TYPES.has(a.account_type))
    .sort((a, b) => a.name.localeCompare(b.name));
}

const selectClass =
  "h-8 w-full max-w-full rounded-md border border-slate-700 bg-slate-900 px-1.5 text-xs text-white";

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

type QueueActionId = "post" | "save" | "review" | "new" | "retry" | "bulk-save" | "bulk-post";

interface QueueActionItem {
  id: QueueActionId;
  label: string;
  hint?: string;
}

function buildQueueActions(status: QbSyncStatus, row: QueueItem): QueueActionItem[] {
  const actions: QueueActionItem[] = [];

  if (status === "pending" || status === "needs_review") {
    actions.push(
      { id: "post", label: "Post", hint: "Approve and post to QuickBooks" },
      { id: "save", label: "Save", hint: "Approve and train without posting" }
    );
  }

  if (status === "pending") {
    actions.push(
      { id: "review", label: "Move to Review" },
      { id: "new", label: "Move to New" }
    );
  } else if (status === "needs_review") {
    if (row.qb_error || row.qb_sync_status === "failed") {
      actions.unshift({ id: "retry", label: "Retry post", hint: "Try posting again" });
    }
    actions.push({ id: "new", label: "Move to New" });
  } else if (status === "auto_approved") {
    actions.push(
      { id: "review", label: "Move to Review" },
      { id: "new", label: "Move to New" }
    );
  }

  return actions;
}

function QueueRowActionMenu({
  row,
  status,
  disabled,
  loading,
  loadingLabel,
  open,
  onOpenChange,
  onAction,
}: {
  row: QueueItem;
  status: QbSyncStatus;
  disabled?: boolean;
  loading?: boolean;
  loadingLabel?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAction: (action: QueueActionId) => void;
}) {
  const actions = buildQueueActions(status, row);
  if (actions.length === 0) return null;

  return (
    <div className="relative">
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-7 gap-1 px-2 text-xs"
        disabled={disabled}
        loading={loading}
        loadingLabel={loadingLabel}
        onClick={() => onOpenChange(!open)}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        {loading ? null : "Actions"}
        {!loading && (
          <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
        )}
      </Button>
      {open && (
        <>
          <button
            type="button"
            className="fixed inset-0 z-10 cursor-default"
            aria-label="Close actions menu"
            onClick={() => onOpenChange(false)}
          />
          <div
            role="menu"
            className="absolute right-0 z-20 mt-1 min-w-[11rem] overflow-hidden rounded-lg border border-slate-700 bg-slate-900 py-1 shadow-xl shadow-black/40"
          >
            {actions.map((action) => (
              <button
                key={action.id}
                type="button"
                role="menuitem"
                className="flex w-full flex-col items-start px-3 py-2 text-left text-xs text-slate-200 hover:bg-slate-800"
                onClick={() => {
                  onOpenChange(false);
                  onAction(action.id);
                }}
              >
                <span className="font-medium text-white">{action.label}</span>
                {action.hint && <span className="text-[10px] text-slate-500">{action.hint}</span>}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function BooksQueueContent() {
  const searchParams = useSearchParams();
  const rawStatus = searchParams.get("status") as QbSyncStatus | null;
  const status: QbSyncStatus =
    rawStatus === "excluded" || rawStatus === "failed"
      ? "needs_review"
      : rawStatus || "unclassified";
  const page = Number(searchParams.get("page") || "1");

  const [qbConnected, setQbConnected] = useState<boolean | null>(null);
  const [qbEnvironment, setQbEnvironment] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<BooksReadiness | null>(null);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [postingCoa, setPostingCoa] = useState<CoaAccount[]>([]);
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
  const [actionKind, setActionKind] = useState<QueueActionId | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [classifying, setClassifying] = useState(false);
  const [openActionMenuId, setOpenActionMenuId] = useState<string | null>(null);
  const showBankColumn = (readiness?.bank_accounts?.length ?? 0) > 1;
  const tableColSpan =
    6 + (showBankColumn ? 1 : 0) + (status === "pending" || status === "needs_review" ? 1 : 0);

  const refreshQueue = useCallback(
    async (statusFilter: QbSyncStatus, pageNum: number) => {
      const [queue, sum] = await Promise.all([
        getBooksQueue(statusFilter, pageNum, 20),
        getBooksSummary(),
      ]);
      setItems(queue.items);
      setTotalPages(queue.total_pages);
      setQueueTotal(queue.total);
      setSummary(sum.counts);
      setCoverage(sum.coverage ?? null);
      setReadiness(sum.readiness ?? null);
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
      await refreshQueue(status, page);
    } catch {
      /* non-blocking */
    } finally {
      setClassifying(false);
      setClassifyProgress(null);
    }
  }, [status, page, refreshQueue]);

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
        await refreshQueue(status, page);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Failed to refresh books queue");
      }
    },
    [status, page, refreshQueue, runClassifyAll]
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

        const [coa, auto, queue] = await Promise.all([
          listCoa(undefined, true),
          sum.automation ? Promise.resolve(null) : getAutomationSettings(),
          getBooksQueue(status, page, 20),
        ]);
        if (cancelled) return;

        setPostingCoa(buildPostingCoa(coa.items));
        if (auto) setAutomation(auto);
        setItems(queue.items);
        setTotalPages(queue.total_pages);
        setQueueTotal(queue.total);
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
        await refreshQueue(status, page);
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
  }, [status, page, bootstrapped, qbConnected, refreshQueue]);

  useEffect(() => {
    setOpenActionMenuId(null);
    setSelected(new Set());
  }, [status, page]);

  function resolveAccountId(row: QueueItem): string | undefined {
    const id = accountEdits[row.id] ?? row.qb_account_id ?? "";
    return id || undefined;
  }

  function selectedRows(): QueueItem[] {
    return items.filter((row) => selected.has(row.id));
  }

  function bulkSelectionStats() {
    const rows = selectedRows();
    const ready = rows.filter((row) => resolveAccountId(row));
    return { rows, ready, missing: rows.length - ready.length };
  }

  const allOnPageSelected =
    items.length > 0 && (status === "pending" || status === "needs_review") && items.every((r) => selected.has(r.id));

  function toggleSelectAllOnPage() {
    if (allOnPageSelected) {
      setSelected(new Set());
      return;
    }
    setSelected(new Set(items.map((r) => r.id)));
  }

  function buildBulkItems(): { transaction_id: string; final_account_id: string }[] {
    return selectedRows()
      .map((row) => {
        const final_account_id = resolveAccountId(row);
        return final_account_id ? { transaction_id: row.id, final_account_id } : null;
      })
      .filter((item): item is { transaction_id: string; final_account_id: string } => item !== null);
  }

  async function handleBulkApprove(post: boolean) {
    const { rows, ready, missing } = bulkSelectionStats();
    if (rows.length === 0) return;
    if (missing > 0) {
      setError(`Select a QuickBooks account for all ${rows.length} rows (${missing} still missing)`);
      return;
    }

    const bulkItems = buildBulkItems();
    const kind: QueueActionId = post ? "bulk-post" : "bulk-save";
    setActionLoading("bulk");
    setActionKind(kind);
    setError(null);
    setInfo(
      post
        ? `Posting ${bulkItems.length} transaction${bulkItems.length === 1 ? "" : "s"} to QuickBooks…`
        : `Saving training for ${bulkItems.length} transaction${bulkItems.length === 1 ? "" : "s"}…`
    );

    try {
      const result = await approveBulk({ items: bulkItems, post });
      const similar = result.similar_updated ?? 0;
      const failed = result.failed ?? 0;
      const approved = result.approved ?? 0;

      if (failed > 0) {
        const detail = result.errors[0]?.error;
        setInfo(
          post
            ? `Posted ${approved}, failed ${failed}${similar > 0 ? ` · ${similar} similar updated` : ""}`
            : `Saved ${approved}, failed ${failed}${similar > 0 ? ` · ${similar} similar updated` : ""}`
        );
        if (detail) setError(detail);
      } else if (post) {
        setInfo(
          similar > 0
            ? `Posted ${approved} to QuickBooks — ${similar} similar transaction${similar === 1 ? "" : "s"} updated`
            : `Posted ${approved} transaction${approved === 1 ? "" : "s"} to QuickBooks`
        );
      } else {
        setInfo(
          similar > 0
            ? `Training saved for ${approved} — ${similar} similar transaction${similar === 1 ? "" : "s"} pre-filled`
            : `Training saved for ${approved} transaction${approved === 1 ? "" : "s"}`
        );
      }

      setSelected(new Set());
      await refreshData();
    } catch (e) {
      setInfo(null);
      setError(e instanceof ApiError ? e.message : post ? "Bulk post failed" : "Bulk save failed");
    } finally {
      setActionLoading(null);
      setActionKind(null);
    }
  }

  async function handleApprove(row: QueueItem, post = true) {
    const accountId = accountEdits[row.id] || row.qb_account_id;
    if (!accountId) {
      setError("Select a QuickBooks account first");
      return;
    }
    const kind: QueueActionId = post ? "post" : "save";
    setActionLoading(row.id);
    setActionKind(kind);
    setError(null);
    setInfo(post ? "Posting to QuickBooks…" : "Saving training…");
    try {
      const result = await approveTransaction(row.id, accountId, post);
      const similar = result.similar_updated ?? 0;
      if (post) {
        setInfo(
          similar > 0
            ? `Posted to QuickBooks — ${similar} similar transaction${similar === 1 ? "" : "s"} updated`
            : "Approved and posted to QuickBooks"
        );
      } else {
        setInfo(
          similar > 0
            ? `Training saved — ${similar} similar transaction${similar === 1 ? "" : "s"} pre-filled`
            : "Training saved — similar payees will be suggested next"
        );
      }
      await refreshData();
    } catch (e) {
      setInfo(null);
      setError(e instanceof ApiError ? e.message : "Approve failed");
    } finally {
      setActionLoading(null);
      setActionKind(null);
    }
  }

  async function handlePost(id: string) {
    setActionLoading(id);
    setActionKind("retry");
    setError(null);
    setInfo("Posting to QuickBooks…");
    try {
      await postTransaction(id);
      setInfo("Transaction posted to QuickBooks");
      await refreshData();
    } catch (e) {
      setInfo(null);
      setError(e instanceof ApiError ? e.message : "Post failed");
    } finally {
      setActionLoading(null);
      setActionKind(null);
    }
  }

  async function handleBulkPost() {
    await handleBulkApprove(true);
  }

  async function handleRevert(id: string, target: RevertTarget) {
    setActionLoading(id);
    setActionKind(target === "needs_review" ? "review" : "new");
    setError(null);
    setInfo("Updating queue…");
    const labels: Record<RevertTarget, string> = {
      needs_review: "Review",
      unclassified: "New",
    };
    try {
      await revertTransaction(id, target);
      setInfo(`Moved to ${labels[target]}`);
      await refreshData();
    } catch (e) {
      setInfo(null);
      setError(e instanceof ApiError ? e.message : "Could not move transaction");
    } finally {
      setActionLoading(null);
      setActionKind(null);
    }
  }

  function handleRowAction(row: QueueItem, action: QueueActionId) {
    switch (action) {
      case "post":
        void handleApprove(row, true);
        break;
      case "save":
        void handleApprove(row, false);
        break;
      case "review":
        void handleRevert(row.id, "needs_review");
        break;
      case "new":
        void handleRevert(row.id, "unclassified");
        break;
      case "retry":
        void handlePost(row.id);
        break;
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
      {actionLoading && actionKind && (
        <div className="flex items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-sm text-blue-200">
          <Spinner size="sm" className="text-blue-300" />
          {actionKind === "bulk-save"
            ? "Saving training for selected transactions…"
            : actionKind === "bulk-post"
              ? "Posting selected transactions to QuickBooks…"
              : actionKind === "save"
                ? "Saving training and updating similar payees…"
                : actionKind === "post" || actionKind === "retry"
                  ? "Posting to QuickBooks…"
                  : "Updating queue…"}
        </div>
      )}
      {info && !actionLoading && (
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
              href={`/books?status=${tab.id}`}
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
      </div>

      {STATUS_TAB_HINTS[status] && (
        <div className="rounded-lg border border-slate-700/50 bg-slate-900/40 px-3 py-2 text-sm text-slate-300">
          {STATUS_TAB_HINTS[status]}
        </div>
      )}

      {classifying && (
        <div className="rounded-lg border border-blue-500/20 bg-blue-950/20 px-3 py-2 text-sm text-blue-200">
          {classifyProgress ?? "Classifying…"}
        </div>
      )}

      {(status === "pending" || status === "needs_review") && selected.size > 0 && (
        <div className="sticky bottom-4 z-20 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-blue-500/30 bg-slate-900/95 px-4 py-3 shadow-lg shadow-black/40 backdrop-blur-sm">
          <div className="min-w-0 text-sm">
            <span className="font-medium text-white">{selected.size} selected</span>
            {(() => {
              const { ready, missing } = bulkSelectionStats();
              if (missing > 0) {
                return (
                  <span className="ml-2 text-amber-400">
                    · {ready.length} ready · {missing} need QB account
                  </span>
                );
              }
              return <span className="ml-2 text-slate-400">· each uses its own QB account</span>;
            })()}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-slate-400"
              disabled={Boolean(actionLoading)}
              onClick={() => setSelected(new Set())}
            >
              Clear
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={Boolean(actionLoading) || bulkSelectionStats().missing > 0}
              loading={actionLoading === "bulk" && actionKind === "bulk-save"}
              loadingLabel="Saving…"
              onClick={() => void handleBulkApprove(false)}
            >
              Save all
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={Boolean(actionLoading) || bulkSelectionStats().missing > 0}
              loading={actionLoading === "bulk" && actionKind === "bulk-post"}
              loadingLabel="Posting…"
              onClick={() => void handleBulkPost()}
            >
              Post all
            </Button>
          </div>
        </div>
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
            {showBankColumn && <col className="w-[6rem]" />}
            <col />
            <col className="w-[5.5rem]" />
            <col className="w-[16%]" />
            <col className="w-[6.5rem]" />
            <col className="w-[5.5rem]" />
          </colgroup>
          <thead>
            <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
              {(status === "pending" || status === "needs_review") && (
                <th className="px-2 py-2">
                  <input
                    type="checkbox"
                    checked={allOnPageSelected}
                    disabled={items.length === 0 || Boolean(actionLoading)}
                    onChange={toggleSelectAllOnPage}
                    className="rounded border-slate-600"
                    aria-label="Select all on this page"
                  />
                </th>
              )}
              <th className="px-2 py-2">Date</th>
              {showBankColumn && <th className="px-2 py-2">Bank</th>}
              <th className="px-2 py-2">Payee</th>
              <th className="px-2 py-2">Kind</th>
              <th className="px-2 py-2">QB Account</th>
              <th className="px-2 py-2 text-right">Amount</th>
              <th className="px-2 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td
                  colSpan={tableColSpan}
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
                const rowBusy = actionLoading === row.id;
                const rowSelected = selected.has(row.id);
                const rowActionLabel =
                  actionKind === "save"
                    ? "Saving…"
                    : actionKind === "post" || actionKind === "retry"
                      ? "Posting…"
                      : "Working…";
                return (
                <tr
                  key={row.id}
                  className={`border-b border-slate-800/50 ${
                    rowBusy
                      ? "bg-blue-950/25"
                      : rowSelected
                        ? "bg-blue-950/15"
                        : "hover:bg-slate-900/40"
                  }`}
                >
                  {(status === "pending" || status === "needs_review") && (
                    <td className="px-2 py-2">
                      <input
                        type="checkbox"
                        checked={selected.has(row.id)}
                        disabled={Boolean(actionLoading)}
                        onChange={() => toggleSelect(row.id)}
                        className="rounded border-slate-600"
                      />
                    </td>
                  )}
                  <td className="px-2 py-2 text-xs text-slate-400">{row.transaction_date.slice(5)}</td>
                  {showBankColumn && (
                    <td
                      className="px-2 py-2 text-xs text-slate-400"
                      title={row.account_name ?? undefined}
                    >
                      <span className="cell-truncate block max-w-[6rem]">
                        {row.account_name || "—"}
                      </span>
                    </td>
                  )}
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
                          row.qb_posting_type !== "refund")
                          ? "bg-emerald-900/40 text-emerald-300"
                          : row.qb_posting_type === "refund"
                            ? "bg-violet-900/40 text-violet-300"
                            : row.qb_posting_type === "fee"
                              ? "bg-amber-900/40 text-amber-300"
                              : row.qb_posting_type === "transfer"
                                ? "bg-slate-800 text-slate-400"
                                : "bg-blue-900/40 text-blue-300"
                      }`}
                    >
                      {kind.type}
                    </span>
                  </td>
                  <td className="px-2 py-2 min-w-0">
                    {(status === "pending" || status === "needs_review") &&
                    postingCoa.length > 0 ? (
                      <select
                        className={selectClass}
                        value={accountEdits[row.id] ?? row.qb_account_id ?? ""}
                        disabled={rowBusy || Boolean(actionLoading)}
                        onChange={(e) =>
                          setAccountEdits((prev) => ({ ...prev, [row.id]: e.target.value }))
                        }
                      >
                        <option value="">Select…</option>
                        {postingCoa.map((a) => (
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
                  <td
                    className={`px-2 py-2 text-right text-xs font-medium tabular-nums ${
                      row.transaction_type === "credit" ? "text-green-400" : "text-white"
                    }`}
                  >
                    {signedAmount(row)}
                  </td>
                  <td className="px-2 py-2">
                    {status === "unclassified" ? (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        disabled={actionLoading === row.id || classifying}
                        onClick={() => refreshData({ classify: true })}
                      >
                        Map
                      </Button>
                    ) : (
                      <QueueRowActionMenu
                        row={row}
                        status={status}
                        disabled={Boolean(actionLoading)}
                        loading={rowBusy}
                        loadingLabel={rowActionLabel}
                        open={openActionMenuId === row.id}
                        onOpenChange={(next) => setOpenActionMenuId(next ? row.id : null)}
                        onAction={(action) => handleRowAction(row, action)}
                      />
                    )}
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
            <Link href={`/books?status=${status}&page=${page - 1}`}>
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
    <Suspense fallback={<PageLoader message="Loading books…" />}>
      <BooksQueueContent />
    </Suspense>
  );
}
