"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertCircle, BookOpen, MoreHorizontal, Plus, RefreshCw } from "lucide-react";
import { QuickBooksConnectButton } from "@/components/accounts/quickbooks-connect-button";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { PageLoader } from "@/components/ui/page-loader";
import { Spinner } from "@/components/ui/spinner";
import {
  approveBulk,
  approveTransaction,
  buildBooksUrl,
  classifyTransactions,
  createQbParty,
  getAutomationSettings,
  getBooksQueue,
  getBooksSummary,
  getQuickBooksStatus,
  listCoa,
  listQbParties,
  parseBooksDateRange,
  postTransaction,
  revertTransaction,
  suggestQbParty,
  syncCoa,
  type AutomationSettings,
  type BooksReadiness,
  type BulkApproveItem,
  type CoaAccount,
  type QbParty,
  type QbPartyType,
  type QbSyncStatus,
  type QueueItem,
  type RevertTarget,
} from "@/lib/books";
import { ApiError } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import { TransactionDateStack } from "@/components/books/transaction-date-stack";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const STATUS_TABS: { id: QbSyncStatus; label: string }[] = [
  { id: "unclassified", label: "New" },
  { id: "pending", label: "Pending" },
  { id: "needs_review", label: "Review" },
  { id: "failed", label: "Failed" },
  { id: "auto_approved", label: "Auto" },
  { id: "posted", label: "Posted" },
];

function queueTabEditable(status: QbSyncStatus): boolean {
  return status === "pending" || status === "needs_review" || status === "failed";
}

type ClosedPeriodDetail = {
  code: "CLOSED_PERIOD";
  transaction_date: string;
  message: string;
};

function parseClosedPeriodError(e: unknown): ClosedPeriodDetail | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const d = e.detail;
  if (typeof d === "object" && d !== null && (d as ClosedPeriodDetail).code === "CLOSED_PERIOD") {
    return d as ClosedPeriodDetail;
  }
  return null;
}

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
  } else if (
    postingType === "balance_sheet" ||
    (postingType === "skip" && reason?.toLowerCase().includes("balance sheet"))
  ) {
    type = "Balance sheet";
  } else if (/transfer in/i.test(category)) {
    type = "Transfer In";
  } else if (/transfer out/i.test(category)) {
    type = "Transfer Out";
  } else {
    type = row.transaction_type === "credit" ? "Credit" : "Debit";
  }

  const direction = directionLabel(row);
  const title = `${direction} · ${type}`;

  return { type, direction, title };
}

type CoaGroup = { label: string; items: CoaAccount[] };

const COA_GROUP_ORDER: { label: string; types: string[] }[] = [
  { label: "Income", types: ["Income", "Other Income"] },
  { label: "Expenses", types: ["Expense", "Other Expense", "Cost of Goods Sold"] },
  {
    label: "Liabilities & cards",
    types: ["Other Current Liability", "Long Term Liability", "Accounts Payable", "Credit Card"],
  },
  { label: "Equity", types: ["Equity"] },
  {
    label: "Assets",
    types: ["Other Current Asset", "Fixed Asset", "Accounts Receivable"],
  },
  { label: "Banks — transfers", types: ["Bank"] },
];

const POSTABLE_ACCOUNT_TYPES = new Set(COA_GROUP_ORDER.flatMap((g) => g.types));

function buildPostingCoaGroups(accounts: CoaAccount[]): CoaGroup[] {
  const postable = accounts.filter(
    (a) => a.account_type && POSTABLE_ACCOUNT_TYPES.has(a.account_type),
  );
  return COA_GROUP_ORDER.map(({ label, types }) => ({
    label,
    items: postable
      .filter((a) => types.includes(a.account_type!))
      .sort((a, b) => a.name.localeCompare(b.name)),
  })).filter((g) => g.items.length > 0);
}

function hasPostingAccounts(groups: CoaGroup[]): boolean {
  return groups.some((g) => g.items.length > 0);
}

function flattenCoaGroups(groups: CoaGroup[]): CoaAccount[] {
  return groups.flatMap((g) => g.items);
}

function partyTypeForAccount(
  row: QueueItem,
  accountId: string | undefined,
  accounts: CoaAccount[]
): QbPartyType | null {
  if (!accountId) return null;
  const acct = accounts.find((a) => a.qb_account_id === accountId);
  if (!acct?.account_type) return null;
  const at = acct.account_type.toLowerCase();
  const pt = (row.qb_posting_type || "").toLowerCase();
  if (pt === "transfer" || pt === "balance_sheet") return null;
  if (pt === "expense" || pt === "fee" || pt === "refund") return "Vendor";
  if (pt === "deposit" && (at === "income" || at === "other income")) return "Customer";
  if (
    row.transaction_type === "debit" &&
    (at === "expense" || at === "other expense" || at === "cost of goods sold")
  ) {
    return "Vendor";
  }
  if (row.transaction_type === "credit" && (at === "income" || at === "other income")) {
    return "Customer";
  }
  return null;
}

function defaultPartyDisplayName(row: QueueItem): string {
  const raw = (row.payee_pattern || row.merchant_name || row.description || "Payee").trim();
  return raw
    .split(/\s+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ")
    .slice(0, 100);
}

const selectClass =
  "h-8 w-full min-w-0 rounded-md border border-slate-700/80 bg-slate-900/90 px-2 text-xs text-slate-200";

const cellPad = "px-3 py-2.5 align-top";

function QuickBooksMappingCell({
  row,
  status,
  rowBusy,
  actionLoading,
  rowAccountId,
  rowPartyType,
  rowParties,
  postingCoaGroups,
  accountEdits,
  partyEdits,
  creatingPartyId,
  onAccountChange,
  onPartyChange,
  onCreateParty,
}: {
  row: QueueItem;
  status: QbSyncStatus;
  rowBusy: boolean;
  actionLoading: string | null;
  rowAccountId: string | undefined;
  rowPartyType: QbPartyType | null;
  rowParties: QbParty[];
  postingCoaGroups: CoaGroup[];
  accountEdits: Record<string, string>;
  partyEdits: Record<string, string>;
  creatingPartyId: string | null;
  onAccountChange: (value: string) => void;
  onPartyChange: (value: string) => void;
  onCreateParty: () => void;
}) {
  const editable = queueTabEditable(status);
  const disabled = rowBusy || Boolean(actionLoading);

  if (!editable || !hasPostingAccounts(postingCoaGroups)) {
    return (
      <div className="space-y-1 text-xs">
        <div className="text-slate-300 truncate" title={row.qb_account_name ?? undefined}>
          {row.qb_account_name || "—"}
        </div>
        {row.qb_party_name ? (
          <div className="text-slate-500 truncate" title={row.qb_party_name}>
            {row.qb_party_name}
          </div>
        ) : null}
      </div>
    );
  }

  const accountValue = accountEdits[row.id] ?? row.qb_account_id ?? "";
  const partyValue = partyEdits[row.id] ?? row.qb_party_id ?? "";
  const partyLabel = rowPartyType === "Customer" ? "Customer" : "Vendor";

  return (
    <div className="space-y-1.5 min-w-[11rem]">
      <select
        className={selectClass}
        value={accountValue}
        disabled={disabled}
        title={flatCoaName(postingCoaGroups, accountValue) ?? "QuickBooks account"}
        onChange={(e) => onAccountChange(e.target.value)}
      >
        <option value="">Account…</option>
        {postingCoaGroups.map((group) => (
          <optgroup key={group.label} label={group.label}>
            {group.items.map((a) => (
              <option key={a.qb_account_id} value={a.qb_account_id}>
                {a.name}
              </option>
            ))}
          </optgroup>
        ))}
      </select>

      {rowPartyType ? (
        <div className="flex items-center gap-1">
          <select
            className={selectClass}
            value={partyValue}
            disabled={disabled || creatingPartyId === row.id || !accountValue}
            title={rowParties.find((p) => p.qb_party_id === partyValue)?.display_name ?? partyLabel}
            onChange={(e) => onPartyChange(e.target.value)}
          >
            <option value="">{partyLabel}…</option>
            {rowParties.map((p) => (
              <option key={p.qb_party_id} value={p.qb_party_id}>
                {p.display_name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-slate-700/80 bg-slate-900/90 text-slate-400 hover:border-slate-600 hover:text-white disabled:opacity-40"
            disabled={disabled || creatingPartyId === row.id || !accountValue}
            title={`Create ${partyLabel} in QuickBooks`}
            onClick={onCreateParty}
          >
            {creatingPartyId === row.id ? (
              <Spinner size="sm" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      ) : (
        <div className="flex h-8 items-center px-0.5 text-[10px] text-slate-600">
          {accountValue ? "N/A for this account" : "Select account above"}
        </div>
      )}
    </div>
  );
}

function flatCoaName(groups: CoaGroup[], accountId: string): string | undefined {
  if (!accountId) return undefined;
  for (const group of groups) {
    const hit = group.items.find((a) => a.qb_account_id === accountId);
    if (hit) return hit.name;
  }
  return undefined;
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

type QueueActionId = "post" | "save" | "review" | "new" | "retry" | "bulk-save" | "bulk-post";

interface QueueActionItem {
  id: QueueActionId;
  label: string;
  hint?: string;
}

function buildQueueActions(status: QbSyncStatus, row: QueueItem): QueueActionItem[] {
  const actions: QueueActionItem[] = [];

  if (queueTabEditable(status)) {
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
  } else if (status === "failed") {
    actions.unshift({ id: "retry", label: "Retry post", hint: "Try posting again with current mapping" });
    actions.push(
      { id: "review", label: "Move to Review" },
      { id: "new", label: "Move to New" }
    );
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
        className="h-8 w-8 shrink-0 p-0"
        disabled={disabled}
        loading={loading}
        loadingLabel={loadingLabel}
        onClick={() => onOpenChange(!open)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label="Row actions"
      >
        {!loading && <MoreHorizontal className="h-4 w-4" />}
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
    rawStatus === "excluded" ? "needs_review" : rawStatus || "unclassified";
  const page = Number(searchParams.get("page") || "1");
  const { dateFrom, dateTo } = parseBooksDateRange(searchParams);
  const dateFilterActive = Boolean(dateFrom || dateTo);

  const [qbConnected, setQbConnected] = useState<boolean | null>(null);
  const [qbEnvironment, setQbEnvironment] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<BooksReadiness | null>(null);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [postingCoaGroups, setPostingCoaGroups] = useState<CoaGroup[]>([]);
  const [flatCoa, setFlatCoa] = useState<CoaAccount[]>([]);
  const [qbVendors, setQbVendors] = useState<QbParty[]>([]);
  const [qbCustomers, setQbCustomers] = useState<QbParty[]>([]);
  const [accountEdits, setAccountEdits] = useState<Record<string, string>>({});
  const [partyEdits, setPartyEdits] = useState<Record<string, string>>({});
  const [creatingPartyId, setCreatingPartyId] = useState<string | null>(null);
  const partySuggestedRef = useRef<Set<string>>(new Set());
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
  const [syncingQb, setSyncingQb] = useState(false);
  const lastQbSyncRef = useRef(0);
  const QB_SYNC_STALE_MS = 2 * 60 * 1000;
  const [openActionMenuId, setOpenActionMenuId] = useState<string | null>(null);
  const [closedPeriodModal, setClosedPeriodModal] = useState<{
    transactionId: string;
    transactionDate: string;
    mode: "post" | "approve";
    row?: QueueItem;
  } | null>(null);
  const [closedPeriodChoice, setClosedPeriodChoice] = useState<"true_date" | "catch_up_today" | null>(null);
  const [closedPeriodReason, setClosedPeriodReason] = useState("");
  const [closedPeriodAck, setClosedPeriodAck] = useState(false);
  const showBankColumn = (readiness?.bank_accounts?.length ?? 0) > 1;
  const tableColSpan =
    6 +
    (showBankColumn ? 1 : 0) +
    (queueTabEditable(status) ? 1 : 0) +
    (status === "failed" ? 1 : 0);

  const refreshQueue = useCallback(
    async (statusFilter: QbSyncStatus, pageNum: number, from?: string, to?: string) => {
      const [queue, sum] = await Promise.all([
        getBooksQueue(statusFilter, pageNum, 20, from || undefined, to || undefined),
        getBooksSummary(from || undefined, to || undefined),
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
        const sum = await getBooksSummary(dateFrom || undefined, dateTo || undefined);
        setCoverage(sum.coverage ?? null);
        setSummary(sum.counts);
        setClassifyProgress(
          remaining > 0
            ? `Classified ${total}… ${remaining} remaining`
            : `Classified ${total} transaction(s)`
        );
        if (result.classified === 0) break;
      }
      await refreshQueue(status, page, dateFrom, dateTo);
    } catch {
      /* non-blocking */
    } finally {
      setClassifying(false);
      setClassifyProgress(null);
    }
  }, [status, page, dateFrom, dateTo, refreshQueue]);

  const syncBooksFromQuickBooks = useCallback(
    async (opts?: { parties?: boolean }) => {
      const syncParties = opts?.parties ?? queueTabEditable(status);
      const coa = await listCoa(undefined, true);
      setPostingCoaGroups(buildPostingCoaGroups(coa.items));
      setFlatCoa(coa.items);

      if (syncParties) {
        try {
          const parties = await listQbParties(true);
          setQbVendors(parties.vendors);
          setQbCustomers(parties.customers);
        } catch {
          try {
            const cached = await listQbParties(false);
            setQbVendors(cached.vendors);
            setQbCustomers(cached.customers);
          } catch {
            /* vendors/customers optional until sync succeeds */
          }
        }
      }

      lastQbSyncRef.current = Date.now();
      return coa;
    },
    [status]
  );

  const handleSyncFromQuickBooks = useCallback(async () => {
    setSyncingQb(true);
    setError(null);
    setInfo(null);
    try {
      await syncBooksFromQuickBooks();
      await refreshQueue(status, page, dateFrom, dateTo);
      setInfo("Synced accounts from QuickBooks");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "QuickBooks sync failed");
    } finally {
      setSyncingQb(false);
    }
  }, [syncBooksFromQuickBooks, refreshQueue, status, page, dateFrom, dateTo]);

  const refreshData = useCallback(
    async (opts?: { classify?: boolean }) => {
      setError(null);
      try {
        if (opts?.classify) {
          await runClassifyAll();
          return;
        }
        const sum = await getBooksSummary(dateFrom || undefined, dateTo || undefined);
        setReadiness(sum.readiness ?? null);
        setSummary(sum.counts);
        setCoverage(sum.coverage ?? null);
        if (sum.automation) setAutomation(sum.automation);
        await refreshQueue(status, page, dateFrom, dateTo);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Failed to refresh books queue");
      }
    },
    [status, page, dateFrom, dateTo, refreshQueue, runClassifyAll]
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

        const sum = await getBooksSummary(dateFrom || undefined, dateTo || undefined);
        if (cancelled) return;
        setReadiness(sum.readiness ?? null);
        setSummary(sum.counts);
        setCoverage(sum.coverage ?? null);
        setAutomation(sum.automation ?? null);

        if (!sum.readiness?.bank_connected) return;

        const [coa, auto, queue] = await Promise.all([
          listCoa(undefined, true),
          sum.automation ? Promise.resolve(null) : getAutomationSettings(),
          getBooksQueue(status, page, 20, dateFrom || undefined, dateTo || undefined),
        ]);
        if (cancelled) return;

        setPostingCoaGroups(buildPostingCoaGroups(coa.items));
        setFlatCoa(coa.items);
        lastQbSyncRef.current = Date.now();
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
        await refreshQueue(status, page, dateFrom, dateTo);
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
  }, [status, page, dateFrom, dateTo, bootstrapped, qbConnected, refreshQueue]);

  useEffect(() => {
    if (!bootstrapped || !qbConnected) return;
    if (!queueTabEditable(status)) return;

    let cancelled = false;
    async function loadQuickBooksData() {
      try {
        await syncBooksFromQuickBooks({ parties: true });
      } catch {
        if (!cancelled) {
          /* keep cached COA if live sync fails */
        }
      }
    }

    void loadQuickBooksData();
    return () => {
      cancelled = true;
    };
  }, [bootstrapped, qbConnected, status, syncBooksFromQuickBooks]);

  useEffect(() => {
    if (!bootstrapped || !qbConnected) return;

    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (Date.now() - lastQbSyncRef.current < QB_SYNC_STALE_MS) return;
      void syncBooksFromQuickBooks({
        parties: queueTabEditable(status),
      }).catch(() => undefined);
    };

    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [bootstrapped, qbConnected, status, syncBooksFromQuickBooks]);

  useEffect(() => {
    setOpenActionMenuId(null);
    setSelected(new Set());
    partySuggestedRef.current.clear();
  }, [status, page]);

  useEffect(() => {
    if (!queueTabEditable(status) || flatCoa.length === 0) return;
    for (const row of items) {
      const accountId = accountEdits[row.id] ?? row.qb_account_id ?? "";
      if (!accountId || partyEdits[row.id] || row.qb_party_id) continue;
      void maybeSuggestParty(row, accountId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, flatCoa, status]);

  function resolveAccountId(row: QueueItem): string | undefined {
    const id = accountEdits[row.id] ?? row.qb_account_id ?? "";
    return id || undefined;
  }

  function resolvePartyId(row: QueueItem): string | undefined {
    const id = partyEdits[row.id] ?? row.qb_party_id ?? "";
    return id || undefined;
  }

  async function maybeSuggestParty(row: QueueItem, accountId: string) {
    const partyType = partyTypeForAccount(row, accountId, flatCoa);
    if (!partyType) return;
    if (partyEdits[row.id] || row.qb_party_id) return;
    const key = `${row.id}:${accountId}`;
    if (partySuggestedRef.current.has(key)) return;
    partySuggestedRef.current.add(key);
    try {
      const suggestion = await suggestQbParty(row.id, accountId);
      setPartyEdits((prev) => ({ ...prev, [row.id]: suggestion.qb_party_id }));
    } catch {
      /* no QB match — user can create or pick manually */
    }
  }

  async function handleCreateParty(row: QueueItem) {
    const accountId = resolveAccountId(row);
    if (!accountId) {
      setError("Select a QuickBooks account first");
      return;
    }
    const partyType = partyTypeForAccount(row, accountId, flatCoa);
    if (!partyType) return;

    setCreatingPartyId(row.id);
    setError(null);
    try {
      const created = await createQbParty(defaultPartyDisplayName(row), partyType);
      const entry: QbParty = {
        id: created.qb_party_id,
        qb_party_id: created.qb_party_id,
        display_name: created.qb_party_name,
        party_type: partyType,
        active: true,
      };
      if (partyType === "Vendor") {
        setQbVendors((prev) =>
          [...prev, entry].sort((a, b) => a.display_name.localeCompare(b.display_name))
        );
      } else {
        setQbCustomers((prev) =>
          [...prev, entry].sort((a, b) => a.display_name.localeCompare(b.display_name))
        );
      }
      setPartyEdits((prev) => ({ ...prev, [row.id]: created.qb_party_id }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to create in QuickBooks");
    } finally {
      setCreatingPartyId(null);
    }
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
    items.length > 0 && queueTabEditable(status) && items.every((r) => selected.has(r.id));

  function toggleSelectAllOnPage() {
    if (allOnPageSelected) {
      setSelected(new Set());
      return;
    }
    setSelected(new Set(items.map((r) => r.id)));
  }

  function buildBulkItems(): BulkApproveItem[] {
    return selectedRows()
      .map((row) => {
        const final_account_id = resolveAccountId(row);
        if (!final_account_id) return null;
        const item: BulkApproveItem = { transaction_id: row.id, final_account_id };
        const partyType = partyTypeForAccount(row, final_account_id, flatCoa);
        const partyId = resolvePartyId(row);
        if (partyType && partyId) {
          item.final_party_id = partyId;
          item.final_party_type = partyType;
        }
        return item;
      })
      .filter((item): item is BulkApproveItem => item !== null);
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
      const failed = result.failed ?? 0;
      const approved = result.approved ?? 0;

      if (failed > 0) {
        const detail = result.errors[0]?.error;
        setInfo(post ? `Posted ${approved}, failed ${failed} — see Failed tab` : `Saved ${approved}, failed ${failed} — see Failed tab`);
        if (detail) setError(detail);
      } else {
        setInfo(
          post
            ? `Posted ${approved} transaction${approved === 1 ? "" : "s"}`
            : `Training saved for ${approved} transaction${approved === 1 ? "" : "s"}`
        );
      }

      setSelected(new Set());
      setAccountEdits({});
      setPartyEdits({});
      partySuggestedRef.current.clear();
      await refreshData();
    } catch (e) {
      setInfo(null);
      setError(e instanceof ApiError ? e.message : post ? "Bulk post failed" : "Bulk save failed");
    } finally {
      setActionLoading(null);
      setActionKind(null);
    }
  }

  async function submitClosedPeriodPost() {
    if (!closedPeriodModal || !closedPeriodChoice) return;
    if (closedPeriodChoice === "true_date" && !closedPeriodAck) {
      setError("Acknowledge prior-period adjustment before posting at the true date");
      return;
    }
    const { transactionId, mode, row } = closedPeriodModal;
    const opts = {
      closedPeriodPath: closedPeriodChoice,
      closedPeriodReason: closedPeriodReason.trim() || undefined,
    };
    setActionLoading(transactionId);
    setActionKind(mode === "post" ? "retry" : "post");
    setError(null);
    try {
      if (mode === "post") {
        await postTransaction(transactionId, opts);
        setInfo("Transaction posted to QuickBooks");
      } else if (row) {
        const accountId = accountEdits[row.id] || row.qb_account_id;
        if (!accountId) {
          setError("Select a QuickBooks account first");
          return;
        }
        const partyType = partyTypeForAccount(row, accountId, flatCoa);
        const partyId = resolvePartyId(row);
        const party =
          partyType && partyId ? { id: partyId, type: partyType as QbPartyType } : undefined;
        await approveTransaction(row.id, accountId, true, party, opts);
        setInfo("Posted to QuickBooks");
      }
      setClosedPeriodModal(null);
      setClosedPeriodChoice(null);
      setClosedPeriodReason("");
      setClosedPeriodAck(false);
      await refreshData();
    } catch (e) {
      setInfo(null);
      if (parseClosedPeriodError(e)) {
        setError("QuickBooks still rejected this date — try catch-up or contact your accountant");
      } else {
        setError(e instanceof ApiError ? e.message : "Post failed");
      }
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
      const partyType = partyTypeForAccount(row, accountId, flatCoa);
      const partyId = resolvePartyId(row);
      const party =
        partyType && partyId ? { id: partyId, type: partyType as QbPartyType } : undefined;
      await approveTransaction(row.id, accountId, post, party);
      if (post) {
        setInfo("Posted to QuickBooks");
      } else {
        setInfo("Training saved");
      }
      setAccountEdits((prev) => {
        const next = { ...prev };
        delete next[row.id];
        return next;
      });
      await refreshData();
    } catch (e) {
      setInfo(null);
      const closed = parseClosedPeriodError(e);
      if (closed && post) {
        setClosedPeriodModal({
          transactionId: row.id,
          transactionDate: closed.transaction_date,
          mode: "approve",
          row,
        });
        setError(null);
      } else {
        setError(e instanceof ApiError ? e.message : "Approve failed");
      }
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
      const closed = parseClosedPeriodError(e);
      if (closed) {
        setClosedPeriodModal({
          transactionId: id,
          transactionDate: closed.transaction_date,
          mode: "post",
        });
        setError(null);
      } else {
        setError(e instanceof ApiError ? e.message : "Post failed");
      }
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
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void handleSyncFromQuickBooks()}
            loading={syncingQb}
            loadingLabel="Syncing…"
            className="text-slate-300"
          >
            <RefreshCw className="mr-1 h-3.5 w-3.5" />
            Sync from QuickBooks
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => refreshData({ classify: true })}
            loading={classifying}
            loadingLabel="Classifying…"
            className="text-slate-300"
          >
            Re-classify
          </Button>
        </div>
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
                ? "Saving training…"
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
              href={buildBooksUrl("/books", { status: tab.id, dateFrom, dateTo })}
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

      {classifying && (
        <div className="rounded-lg border border-blue-500/20 bg-blue-950/20 px-3 py-2 text-sm text-blue-200">
          {classifyProgress ?? "Classifying…"}
        </div>
      )}

      {queueTabEditable(status) && selected.size > 0 && (
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

      <div className="relative overflow-x-auto rounded-xl border border-slate-800/70">
        {queueLoading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-950/55 backdrop-blur-[1px]">
            <PageLoader variant="compact" message="" />
          </div>
        )}
        <table
          className={`min-w-[960px] w-full text-sm transition-opacity ${queueLoading ? "pointer-events-none opacity-40" : ""}`}
        >
          <colgroup>
            {queueTabEditable(status) && <col className="w-10" />}
            <col className="w-[7.5rem]" />
            {showBankColumn && <col className="w-[5.5rem]" />}
            <col className="w-[18%]" />
            <col className="w-[4.75rem]" />
            <col className="w-[26%]" />
            {status === "failed" && <col className="min-w-[12rem]" />}
            <col className="w-[7.5rem]" />
            <col className="w-10" />
          </colgroup>
          <thead>
            <tr className="border-b border-slate-800 text-left text-[11px] font-medium uppercase tracking-wide text-slate-500">
              {queueTabEditable(status) && (
                <th className={`${cellPad} pb-2`}>
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
              <th className={`${cellPad} pb-2`}>Date</th>
              {showBankColumn && <th className={`${cellPad} pb-2`}>Bank</th>}
              <th className={`${cellPad} pb-2`}>Payee</th>
              <th className={`${cellPad} pb-2`}>Kind</th>
              <th className={`${cellPad} pb-2`}>
                <span className="block">QuickBooks</span>
                <span className="mt-0.5 block text-[10px] font-normal normal-case tracking-normal text-slate-600">
                  Account · {queueTabEditable(status) ? "Vendor / customer" : "Mapping"}
                </span>
              </th>
              {status === "failed" && <th className={`${cellPad} pb-2`}>Error</th>}
              <th className={`${cellPad} pb-2 text-right`}>Amount</th>
              <th className={`${cellPad} pb-2`}>
                <span className="sr-only">Actions</span>
              </th>
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
                const rowAccountId = resolveAccountId(row);
                const rowPartyType = partyTypeForAccount(row, rowAccountId, flatCoa);
                const rowParties = rowPartyType === "Vendor" ? qbVendors : rowPartyType === "Customer" ? qbCustomers : [];
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
                  {queueTabEditable(status) && (
                    <td className={cellPad}>
                      <input
                        type="checkbox"
                        checked={selected.has(row.id)}
                        disabled={Boolean(actionLoading)}
                        onChange={() => toggleSelect(row.id)}
                        className="rounded border-slate-600"
                      />
                    </td>
                  )}
                  <td className={cellPad}>
                    <TransactionDateStack
                      transactionDate={row.transaction_date}
                      postedDate={row.posted_date ?? row.qb_posted_at}
                      postingLagDays={row.posting_lag_days}
                      unposted={status !== "posted" && !row.qb_posted_at && !row.posted_date}
                    />
                  </td>
                  {showBankColumn && (
                    <td className={`${cellPad} text-xs text-slate-500`} title={row.account_name ?? undefined}>
                      <span className="block truncate">{row.account_name || "—"}</span>
                    </td>
                  )}
                  <td className={`${cellPad} min-w-0 max-w-[14rem]`}>
                    <div
                      className="truncate font-medium text-white"
                      title={[row.merchant_name, row.description].filter(Boolean).join(" · ") || undefined}
                    >
                      {row.merchant_name || row.description || "—"}
                    </div>
                  </td>
                  <td className={cellPad} title={kind.title}>
                    <span
                      className={`inline-block max-w-full truncate rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        row.qb_posting_type === "deposit" ||
                        (row.transaction_type === "credit" &&
                          row.qb_posting_type !== "refund" &&
                          row.qb_posting_type !== "balance_sheet")
                          ? "bg-emerald-900/40 text-emerald-300"
                          : row.qb_posting_type === "refund"
                            ? "bg-violet-900/40 text-violet-300"
                            : row.qb_posting_type === "fee"
                              ? "bg-amber-900/40 text-amber-300"
                              : row.qb_posting_type === "transfer"
                                ? "bg-slate-800 text-slate-400"
                                : row.qb_posting_type === "balance_sheet"
                                  ? "bg-cyan-900/40 text-cyan-300"
                                  : "bg-blue-900/40 text-blue-300"
                      }`}
                    >
                      {kind.type}
                    </span>
                  </td>
                  <td className={cellPad}>
                    <QuickBooksMappingCell
                      row={row}
                      status={status}
                      rowBusy={rowBusy}
                      actionLoading={actionLoading}
                      rowAccountId={rowAccountId}
                      rowPartyType={rowPartyType}
                      rowParties={rowParties}
                      postingCoaGroups={postingCoaGroups}
                      accountEdits={accountEdits}
                      partyEdits={partyEdits}
                      creatingPartyId={creatingPartyId}
                      onAccountChange={(value) => {
                        setAccountEdits((prev) => ({ ...prev, [row.id]: value }));
                        if (value) void maybeSuggestParty(row, value);
                      }}
                      onPartyChange={(value) =>
                        setPartyEdits((prev) => ({ ...prev, [row.id]: value }))
                      }
                      onCreateParty={() => void handleCreateParty(row)}
                    />
                  </td>
                  {status === "failed" && (
                    <td className={`${cellPad} max-w-xs text-xs text-red-300`}>
                      <p className="line-clamp-3" title={row.qb_error || row.qb_confidence_reason || undefined}>
                        {row.qb_error || row.qb_confidence_reason || "Post failed"}
                      </p>
                    </td>
                  )}
                  <td
                    className={`${cellPad} text-right text-xs font-medium tabular-nums whitespace-nowrap ${
                      row.transaction_type === "credit" ? "text-green-400" : "text-white"
                    }`}
                  >
                    {signedAmount(row)}
                  </td>
                  <td className={`${cellPad} w-10`}>
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

      {(totalPages > 1 || (dateFilterActive && queueTotal > 0)) && (
        <div className="flex justify-center gap-2">
          {page > 1 && (
            <Link href={buildBooksUrl("/books", { status, page: page - 1, dateFrom, dateTo })}>
              <Button variant="outline" size="sm">
                Previous
              </Button>
            </Link>
          )}
          <span className="flex items-center px-3 text-sm text-slate-500">
            Showing {(page - 1) * 20 + 1}–{Math.min(page * 20, queueTotal)} of {queueTotal}
            {dateFilterActive ? " in period" : ""}
            {totalPages > 1 ? ` · Page ${page} of ${totalPages}` : ""}
          </span>
          {page < totalPages && (
            <Link href={buildBooksUrl("/books", { status, page: page + 1, dateFrom, dateTo })}>
              <Button variant="outline" size="sm">
                Next
              </Button>
            </Link>
          )}
        </div>
      )}

      <Dialog
        open={closedPeriodModal !== null}
        onOpenChange={(open) => {
          if (!open) {
            setClosedPeriodModal(null);
            setClosedPeriodChoice(null);
            setClosedPeriodReason("");
            setClosedPeriodAck(false);
          }
        }}
      >
        <DialogContent className="border-slate-800 bg-slate-900 text-white sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Closed accounting period</DialogTitle>
            <DialogDescription className="text-slate-400">
              This transaction is dated{" "}
              <span className="font-medium text-white">{closedPeriodModal?.transactionDate}</span>, but
              QuickBooks has closed that period. Choose how to post it.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <label className="flex cursor-pointer gap-3 rounded-lg border border-slate-700 p-3 hover:bg-slate-800/50">
              <input
                type="radio"
                name="closedPeriodPath"
                checked={closedPeriodChoice === "true_date"}
                onChange={() => setClosedPeriodChoice("true_date")}
                className="mt-1"
              />
              <span>
                <span className="font-medium text-white">Post at true transaction date</span>
                <span className="mt-1 block text-slate-400">
                  Prior-period adjustment — requires accountant acknowledgment.
                </span>
              </span>
            </label>
            {closedPeriodChoice === "true_date" && (
              <label className="flex items-start gap-2 pl-1 text-slate-300">
                <input
                  type="checkbox"
                  checked={closedPeriodAck}
                  onChange={(e) => setClosedPeriodAck(e.target.checked)}
                  className="mt-0.5 rounded border-slate-600"
                />
                I understand this may reopen or adjust a closed period in QuickBooks.
              </label>
            )}
            <label className="flex cursor-pointer gap-3 rounded-lg border border-slate-700 p-3 hover:bg-slate-800/50">
              <input
                type="radio"
                name="closedPeriodPath"
                checked={closedPeriodChoice === "catch_up_today"}
                onChange={() => setClosedPeriodChoice("catch_up_today")}
                className="mt-1"
              />
              <span>
                <span className="font-medium text-white">Post as catch-up (today&apos;s date)</span>
                <span className="mt-1 block text-slate-400">
                  TxnDate will be today; the bank transaction date is preserved in FinSight for matching.
                </span>
              </span>
            </label>
            <label className="block text-slate-400">
              Reason (optional)
              <input
                className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-white"
                value={closedPeriodReason}
                onChange={(e) => setClosedPeriodReason(e.target.value)}
                placeholder="e.g. Month-end close completed before review"
              />
            </label>
          </div>
          <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="outline" onClick={() => setClosedPeriodModal(null)}>
              Cancel
            </Button>
            <Button
              disabled={
                !closedPeriodChoice ||
                (closedPeriodChoice === "true_date" && !closedPeriodAck) ||
                Boolean(actionLoading)
              }
              onClick={() => void submitClosedPeriodPost()}
            >
              Confirm and post
            </Button>
          </div>
        </DialogContent>
      </Dialog>
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
