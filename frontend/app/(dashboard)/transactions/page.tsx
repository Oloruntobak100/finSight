"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { DateInput } from "@/components/ui/date-input";
import { Input } from "@/components/ui/input";
import { formatCurrency } from "@/lib/utils";
import {
  formatCategoryLabel,
  getCategoryDisplay,
  getTransactionDetails,
  truncateText,
  type TransactionDetails,
} from "@/lib/transaction-display";
import {
  getDefaultVisibleColumns,
  loadVisibleColumns,
  saveVisibleColumns,
  TRANSACTION_COLUMNS,
  type TransactionColumnId,
} from "@/lib/transaction-columns";
import { ColumnPicker } from "@/components/transactions/column-picker";
import { TableRowSkeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

interface Account {
  id: string;
  account_name: string;
  provider: string;
}

interface Transaction {
  id: string;
  account_id: string | null;
  account_name: string | null;
  transaction_date: string;
  merchant_name: string | null;
  description: string | null;
  category: string | null;
  sub_category: string | null;
  amount: number;
  currency: string;
  transaction_type: "debit" | "credit";
  is_recurring: boolean;
  is_synthetic?: boolean;
  source_provider?: string;
  details?: TransactionDetails | null;
}

interface TransactionList {
  items: Transaction[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

const cardClass = "rounded-xl border border-slate-800/70 bg-transparent p-5";

const selectClass =
  "h-10 w-full rounded-md border border-slate-700 bg-slate-900 px-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500";

const COLUMN_HEADERS: Record<TransactionColumnId, string> = {
  date: "Date",
  bank: "Bank",
  type: "Type",
  direction: "Direction",
  counterparty: "Counterparty",
  channel: "Channel",
  category: "Category",
  reference: "Reference",
  narration: "Narration",
  amount: "Amount",
};

export default function TransactionsPage() {
  return (
    <Suspense
      fallback={
        <div className="page-enter space-y-6">
          <TableRowSkeleton cols={6} />
        </div>
      }
    >
      <TransactionsPageContent />
    </Suspense>
  );
}

function TransactionsPageContent() {
  const searchParams = useSearchParams();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [columnPickerOpen, setColumnPickerOpen] = useState(false);
  const [visibleColumns, setVisibleColumns] = useState(getDefaultVisibleColumns);
  const requestId = useRef(0);

  const [accountId, setAccountId] = useState("");
  const [transactionType, setTransactionType] = useState("");
  const [category, setCategory] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [recurringOnly, setRecurringOnly] = useState(false);
  const [syntheticFilter, setSyntheticFilter] = useState("");

  const accountMap = Object.fromEntries(accounts.map((a) => [a.id, a.account_name]));
  const activeColumns = TRANSACTION_COLUMNS.filter((col) => visibleColumns[col.id]);

  function updateVisibleColumns(next: Record<TransactionColumnId, boolean>) {
    setVisibleColumns(next);
    saveVisibleColumns(next);
  }

  useEffect(() => {
    setVisibleColumns(loadVisibleColumns());
  }, []);

  useEffect(() => {
    const id = searchParams.get("account_id");
    if (id) {
      setAccountId(id);
      setPage(1);
    }
  }, [searchParams]);

  const loadTransactions = useCallback(async (options?: { quiet?: boolean }) => {
    const id = ++requestId.current;
    if (!options?.quiet) {
      setLoading(true);
      setLoadError(null);
    }
    const params = new URLSearchParams({ page: String(page), limit: "25" });
    if (accountId) params.set("account_id", accountId);
    if (transactionType) params.set("transaction_type", transactionType);
    if (category) params.set("category", category);
    if (search.trim()) params.set("search", search.trim());
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (recurringOnly) params.set("is_recurring", "true");
    if (syntheticFilter === "real") params.set("is_synthetic", "false");
    if (syntheticFilter === "synthetic") params.set("is_synthetic", "true");

    try {
      const data = await apiFetch<TransactionList>(`/transactions?${params}`);
      if (id !== requestId.current) return;
      setTransactions(data.items);
      setTotal(data.total);
      setTotalPages(data.total_pages);
    } catch (err) {
      if (id !== requestId.current) return;
      setTransactions([]);
      setTotal(0);
      setTotalPages(1);
      if (!options?.quiet) {
        const msg =
          err instanceof Error && err.message
            ? err.message
            : "Could not load transactions. Make sure the backend is running.";
        setLoadError(msg);
      }
    } finally {
      if (!options?.quiet && id === requestId.current) {
        setLoading(false);
      }
    }
  }, [page, accountId, transactionType, category, search, dateFrom, dateTo, recurringOnly, syntheticFilter]);

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput), 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    void (async () => {
      try {
        const metaRes = await apiFetch<{ categories: string[]; accounts: Account[] }>("/transactions/meta");
        setAccounts(metaRes.accounts ?? []);
        setCategories(metaRes.categories ?? []);
      } catch {
        try {
          const [accountsRes, categoriesRes] = await Promise.all([
            apiFetch<{ accounts: Account[] }>("/oauth/accounts").catch(() => ({ accounts: [] })),
            apiFetch<{ categories: string[] }>("/transactions/meta").catch(() => ({ categories: [] })),
          ]);
          setAccounts(accountsRes.accounts ?? []);
          setCategories(categoriesRes.categories ?? []);
        } catch {
          setAccounts([]);
          setCategories([]);
        }
      }
    })();
  }, []);

  useEffect(() => {
    loadTransactions();
  }, [loadTransactions]);

  function resetFilters() {
    setAccountId("");
    setTransactionType("");
    setCategory("");
    setSearchInput("");
    setSearch("");
    setDateFrom("");
    setDateTo("");
    setRecurringOnly(false);
    setSyntheticFilter("");
    setPage(1);
    if (typeof window !== "undefined" && searchParams.get("account_id")) {
      window.history.replaceState(null, "", "/transactions");
    }
  }

  function renderCell(columnId: TransactionColumnId, txn: Transaction) {
    const details = getTransactionDetails(txn);
    const categoryDisplay = getCategoryDisplay(txn);
    const isIncoming = txn.transaction_type === "credit";
    const narration =
      details.narration ||
      (txn.source_provider === "mono" ? txn.description : null) ||
      txn.description;

    switch (columnId) {
      case "date":
        return <td key={columnId} className="py-3 pr-3 text-slate-400">{txn.transaction_date}</td>;
      case "bank":
        return (
          <td key={columnId} className="py-3 pr-3 text-slate-300">
            {txn.account_name || (txn.account_id && accountMap[txn.account_id]) || "—"}
          </td>
        );
      case "type":
        return (
          <td key={columnId} className="py-3 pr-3 capitalize">
            <span className={isIncoming ? "font-medium text-green-400" : "font-medium text-slate-200"}>
              {txn.transaction_type}
            </span>
          </td>
        );
      case "direction":
        return (
          <td key={columnId} className="py-3 pr-3">
            <div className={isIncoming ? "font-medium text-green-400" : "font-medium text-slate-200"}>
              {isIncoming ? "Incoming" : "Outgoing"}
            </div>
          </td>
        );
      case "counterparty":
        return (
          <td key={columnId} className="max-w-0 py-3 pr-3">
            <div className="cell-truncate font-medium text-white" title={details.counterparty || undefined}>
              {details.counterparty || "—"}
            </div>
            {(details.summary || details.counterparty_bank) && (
              <p
                className="cell-truncate mt-0.5 text-xs text-slate-500"
                title={[details.summary, details.counterparty_bank].filter(Boolean).join(" · ")}
              >
                {details.summary || details.counterparty_bank}
              </p>
            )}
            {txn.is_recurring && (
              <span className="mt-0.5 block text-[10px] text-amber-400/90">Recurring</span>
            )}
            {txn.is_synthetic && (
              <span className="mt-0.5 block text-[10px] text-amber-400/80">Synthetic</span>
            )}
          </td>
        );
      case "channel":
        return (
          <td key={columnId} className="py-3 pr-3 text-slate-300">
            <div>{details.channel || "—"}</div>
            {details.payment_method && (
              <p className="mt-0.5 text-xs text-slate-500">{details.payment_method}</p>
            )}
            {details.payment_processor && (
              <p className="mt-0.5 text-xs text-slate-600">{details.payment_processor}</p>
            )}
            {details.reason && (
              <p className="mt-0.5 text-xs text-slate-600">{details.reason}</p>
            )}
          </td>
        );
      case "category":
        return (
          <td key={columnId} className="py-3 pr-3">
            <div className="text-slate-300">{categoryDisplay.primary}</div>
            {categoryDisplay.secondary && (
              <p className="mt-0.5 text-xs text-slate-500">{categoryDisplay.secondary}</p>
            )}
          </td>
        );
      case "reference":
        return (
          <td key={columnId} className="py-3 pr-3 font-mono text-xs text-slate-400">
            {details.reference || "—"}
          </td>
        );
      case "narration":
        return (
          <td key={columnId} className="max-w-[220px] py-3 pr-3">
            <span className="block truncate text-xs text-slate-500" title={narration || undefined}>
              {truncateText(narration, 56)}
            </span>
          </td>
        );
      case "amount":
        return (
          <td
            key={columnId}
            className={`py-3 text-right font-medium ${
              isIncoming ? "text-green-400" : "text-white"
            }`}
          >
            {isIncoming ? "+" : "-"}
            {formatCurrency(txn.amount, txn.currency)}
          </td>
        );
      default:
        return null;
    }
  }

  return (
    <div className="page-enter min-w-0 space-y-4">
      <div>
        <h1 className="text-xl font-bold text-white md:text-2xl">Transactions</h1>
        <p className="text-sm text-slate-500">
          {accountId ? `Filtered · ${accountMap[accountId] || "selected account"}` : "All connected accounts"}
        </p>
      </div>

      <div className={cardClass}>
        <h2 className="mb-4 text-base font-semibold text-white">Filters</h2>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="mb-1.5 block text-xs text-slate-400">Bank</label>
            <select
              className={selectClass}
              value={accountId}
              onChange={(e) => {
                setAccountId(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All banks</option>
              {accounts.map((acc) => (
                <option key={acc.id} value={acc.id}>
                  {acc.account_name || acc.provider}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-xs text-slate-400">Type</label>
            <select
              className={selectClass}
              value={transactionType}
              onChange={(e) => {
                setTransactionType(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All types</option>
              <option value="debit">Expense (debit)</option>
              <option value="credit">Income (credit)</option>
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-xs text-slate-400">Category</label>
            <select
              className={selectClass}
              value={category}
              onChange={(e) => {
                setCategory(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All categories</option>
              {categories.map((cat) => (
                <option key={cat} value={cat}>
                  {formatCategoryLabel(cat)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-xs text-slate-400">Source</label>
            <select
              className={selectClass}
              value={syntheticFilter}
              onChange={(e) => {
                setSyntheticFilter(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All sources</option>
              <option value="real">Real only</option>
              <option value="synthetic">Synthetic only</option>
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-xs text-slate-400">Search</label>
            <Input
              placeholder="Counterparty, narration, or description"
              value={searchInput}
              onChange={(e) => {
                setSearchInput(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs text-slate-400">From date</label>
            <DateInput
              value={dateFrom}
              onChange={(e) => {
                setDateFrom(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs text-slate-400">To date</label>
            <DateInput
              value={dateTo}
              onChange={(e) => {
                setDateTo(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <div className="flex items-end">
            <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={recurringOnly}
                onChange={(e) => {
                  setRecurringOnly(e.target.checked);
                  setPage(1);
                }}
                className="rounded border-slate-600 bg-slate-900"
              />
              Recurring only
            </label>
          </div>
          <div className="flex items-end">
            <Button variant="outline" onClick={resetFilters} className="w-full">
              Clear filters
            </Button>
          </div>
        </div>
      </div>

      {loadError && (
        <p className="rounded-lg border border-red-900/50 bg-red-950/30 px-4 py-3 text-sm text-red-300">
          {loadError}
        </p>
      )}

      <div className={cardClass}>
        <div className="mb-4 flex flex-row flex-wrap items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
            {loading && <Spinner size="sm" className="text-blue-400" />}
            {loading ? "Loading transactions…" : `${total} transaction${total === 1 ? "" : "s"}`}
          </h2>
          <div className="flex items-center gap-2">
            <ColumnPicker
              open={columnPickerOpen}
              onOpenChange={setColumnPickerOpen}
              visible={visibleColumns}
              onChange={updateVisibleColumns}
            />
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1 || loading}
              onClick={() => setPage((p) => p - 1)}
            >
              Previous
            </Button>
            <span className="text-sm text-slate-400">
              Page {page} of {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages || loading}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </div>
        <div className="overflow-hidden">
          <table className="table-fit text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-slate-400">
                {activeColumns.map((col) => (
                  <th
                    key={col.id}
                    className={`pb-2 pr-3 ${col.id === "amount" ? "text-right" : ""}`}
                  >
                    {COLUMN_HEADERS[col.id]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <TableRowSkeleton key={i} cols={activeColumns.length} />
                ))
              ) : transactions.length === 0 ? (
                <tr>
                  <td colSpan={activeColumns.length} className="py-8 text-center text-slate-500">
                    No transactions match your filters
                  </td>
                </tr>
              ) : (
                transactions.map((txn) => (
                  <tr key={txn.id} className="border-b border-slate-800/50 align-top">
                    {activeColumns.map((col) => renderCell(col.id, txn))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
