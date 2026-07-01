"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { QuickBooksConnectButton } from "@/components/accounts/quickbooks-connect-button";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { PageLoader } from "@/components/ui/page-loader";
import { Spinner } from "@/components/ui/spinner";
import { apiFetch, ApiError } from "@/lib/api";
import {
  getOpeningBalancePreview,
  getQuickBooksStatus,
  listCoa,
  listMappings,
  postOpeningBalance,
  syncCoa,
  upsertMapping,
  type AccountMapping,
  type CoaAccount,
  type OpeningBalancePreview,
} from "@/lib/books";
import { formatCurrency } from "@/lib/utils";
import { providerDisplayName } from "@/lib/provider-labels";

interface BankAccount {
  id: string;
  account_name: string;
  provider: string;
  external_account_id?: string | null;
}

const selectClass =
  "h-10 w-full rounded-md border border-slate-700 bg-slate-900 px-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500";

function OpeningBalancePanel({
  accountId,
  qbAccountId,
  onPosted,
}: {
  accountId: string;
  qbAccountId: string;
  onPosted: () => void;
}) {
  const [preview, setPreview] = useState<OpeningBalancePreview | null>(null);
  const [amount, setAmount] = useState("");
  const [asOf, setAsOf] = useState("");
  const [loading, setLoading] = useState(false);
  const [posting, setPosting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const loadPreview = useCallback(async () => {
    if (!qbAccountId) return;
    setLoading(true);
    setLocalError(null);
    try {
      const p = await getOpeningBalancePreview(accountId);
      setPreview(p);
      if (p.opening_balance_amount != null) {
        setAmount(String(p.opening_balance_amount));
      } else if (p.suggested_mono_balance > 0) {
        setAmount(String(p.suggested_mono_balance));
      }
      if (p.opening_balance_as_of) {
        setAsOf(p.opening_balance_as_of.slice(0, 10));
      } else {
        setAsOf(new Date().toISOString().slice(0, 10));
      }
    } catch (e) {
      setLocalError(e instanceof ApiError ? e.message : "Failed to load opening balance preview");
    } finally {
      setLoading(false);
    }
  }, [accountId, qbAccountId]);

  useEffect(() => {
    void loadPreview();
  }, [loadPreview]);

  async function handlePost() {
    const parsed = parseFloat(amount);
    if (!parsed || parsed <= 0) {
      setLocalError("Enter a positive opening balance amount");
      return;
    }
    if (!asOf) {
      setLocalError("Select an as-of date");
      return;
    }
    setPosting(true);
    setLocalError(null);
    try {
      await postOpeningBalance(accountId, {
        amount: parsed,
        as_of_date: asOf,
        qb_bank_account_id: qbAccountId,
      });
      onPosted();
      await loadPreview();
    } catch (e) {
      setLocalError(e instanceof ApiError ? e.message : "Failed to post opening balance");
    } finally {
      setPosting(false);
    }
  }

  if (!qbAccountId) return null;

  return (
    <div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/60 p-4">
      <p className="text-sm font-medium text-white">Opening balance</p>
      <p className="mt-1 text-xs text-slate-500">
        Post a journal entry (Debit bank · Credit Opening Balance Equity) so QuickBooks book balance
        aligns with the bank at conversion.
      </p>
      {loading && !preview ? (
        <p className="mt-2 text-xs text-slate-500">Loading suggested balance…</p>
      ) : (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <p className="text-xs text-slate-500">
              Suggested from bank ({preview?.mono_balance_source ?? "—"})
            </p>
            <p className="text-sm font-medium text-white">
              {formatCurrency(preview?.suggested_mono_balance ?? 0, preview?.currency ?? "NGN")}
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-500">QBO current balance</p>
            <p className="text-sm font-medium text-white">
              {preview?.qbo_current_balance != null
                ? formatCurrency(preview.qbo_current_balance, preview?.currency ?? "NGN")
                : "—"}
            </p>
          </div>
          <label className="text-xs text-slate-400">
            Amount (NGN)
            <input
              type="number"
              min="0"
              step="0.01"
              className={`${selectClass} mt-1`}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              disabled={preview?.already_posted}
            />
          </label>
          <label className="text-xs text-slate-400">
            As-of date
            <input
              type="date"
              className={`${selectClass} mt-1`}
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              disabled={preview?.already_posted}
            />
          </label>
        </div>
      )}
      {preview?.already_posted && (
        <p className="mt-2 text-xs text-emerald-400">
          Opening balance posted (JE {preview.opening_balance_qb_journal_id ?? "—"})
        </p>
      )}
      {localError && <p className="mt-2 text-xs text-red-400">{localError}</p>}
      {!preview?.already_posted && (
        <Button className="mt-3" size="sm" disabled={posting || loading} onClick={() => void handlePost()}>
          {posting ? <Spinner size="sm" className="mr-2" /> : null}
          Post opening balance to QuickBooks
        </Button>
      )}
    </div>
  );
}

export default function BooksMappingsPage() {
  const [qbConnected, setQbConnected] = useState<boolean | null>(null);
  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [coa, setCoa] = useState<CoaAccount[]>([]);
  const [mappings, setMappings] = useState<AccountMapping[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [newCategory, setNewCategory] = useState("");
  const [newCategoryQb, setNewCategoryQb] = useState("");

  const bankCoa = coa.filter((a) => a.account_type === "Bank");
  const expenseCoa = coa.filter((a) => a.account_type === "Expense");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qb = await getQuickBooksStatus();
      setQbConnected(qb.connected);
      if (!qb.connected) return;

      // Mappings endpoint syncs COA from QuickBooks; then read the refreshed cache.
      const [mapRes, meta] = await Promise.all([
        listMappings(),
        apiFetch<{ accounts: BankAccount[]; categories: string[] }>("/transactions/meta"),
      ]);
      const coaRes = await listCoa();
      setCoa(coaRes.items);
      setMappings(mapRes);
      setBankAccounts(meta.accounts.filter((a) => a.provider === "plaid" || a.provider === "mono"));
      setCategories(meta.categories);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load mappings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSyncCoa() {
    setSyncing(true);
    setError(null);
    try {
      const result = await syncCoa();
      const removedNote =
        result.removed && result.removed > 0
          ? `, removed ${result.removed} stale account(s)`
          : "";
      setMessage(`Synced ${result.synced} accounts from QuickBooks${removedNote}`);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "COA sync failed");
    } finally {
      setSyncing(false);
    }
  }

  async function saveBankMapping(finsightKey: string, qbAccountId: string) {
    const account = bankCoa.find((a) => a.qb_account_id === qbAccountId);
    try {
      await upsertMapping({
        mapping_type: "bank_account",
        finsight_key: finsightKey,
        qb_account_id: qbAccountId,
        qb_account_name: account?.name,
      });
      setMessage("Bank mapping saved");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Save failed");
    }
  }

  async function saveCategoryMapping(category: string, qbAccountId: string) {
    const account = expenseCoa.find((a) => a.qb_account_id === qbAccountId);
    try {
      await upsertMapping({
        mapping_type: "category",
        finsight_key: category,
        qb_account_id: qbAccountId,
        qb_account_name: account?.name,
      });
      setMessage("Category mapping saved");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Save failed");
    }
  }

  function bankMappingKey(bank: BankAccount): string {
    return bank.external_account_id || bank.id;
  }

  function bankMappingFor(bank: BankAccount): string {
    const stableKey = bankMappingKey(bank);
    const byStable = mappings.find(
      (m) => m.mapping_type === "bank_account" && m.finsight_key === stableKey,
    );
    if (byStable?.qb_account_id) return byStable.qb_account_id;
    return (
      mappings.find((m) => m.mapping_type === "bank_account" && m.finsight_key === bank.id)
        ?.qb_account_id ?? ""
    );
  }

  function categoryMappingFor(category: string): string {
    return mappings.find((m) => m.mapping_type === "category" && m.finsight_key === category)
      ?.qb_account_id ?? "";
  }

  if (loading) {
    return <PageLoader message="Loading mappings…" />;
  }

  if (!qbConnected) {
    return (
      <Card className="border-slate-800 bg-slate-900/50">
        <CardHeader>
          <CardTitle>Connect QuickBooks</CardTitle>
        </CardHeader>
        <QuickBooksConnectButton />
      </Card>
    );
  }

  return (
    <div className="page-enter space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Books Mappings</h1>
          <p className="text-slate-400">
            Map FinSight bank accounts and categories to your QuickBooks Chart of Accounts.
          </p>
        </div>
        <Button onClick={handleSyncCoa} disabled={syncing} variant="outline">
          {syncing ? <Spinner size="sm" className="mr-2" /> : <RefreshCw className="mr-2 h-4 w-4" />}
          Sync Chart of Accounts
        </Button>
      </div>

      {message && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">
          {message}
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      <Card className="border-slate-800 bg-slate-900/50">
        <CardHeader>
          <CardTitle className="text-base">Bank account mapping</CardTitle>
        </CardHeader>
        <div className="space-y-4">
          {bankAccounts.length === 0 ? (
            <p className="text-sm text-slate-500">Connect a bank account first.</p>
          ) : (
            bankAccounts.map((bank) => (
              <div key={bank.id} className="border-b border-slate-800/60 pb-4 last:border-0 last:pb-0">
                <div className="grid gap-2 md:grid-cols-2 md:items-center">
                  <div>
                    <p className="font-medium text-white">{bank.account_name}</p>
                    <p className="text-xs text-slate-500">{providerDisplayName(bank.provider)}</p>
                  </div>
                  <select
                    className={selectClass}
                    value={bankMappingFor(bank)}
                    onChange={(e) =>
                      saveBankMapping(bankMappingKey(bank), e.target.value)
                    }
                  >
                    <option value="">Select QB bank account…</option>
                    {bankCoa.map((a) => (
                      <option key={a.qb_account_id} value={a.qb_account_id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                </div>
                {bankMappingFor(bank) ? (
                  <OpeningBalancePanel
                    accountId={bank.id}
                    qbAccountId={bankMappingFor(bank)}
                    onPosted={() => setMessage("Opening balance posted to QuickBooks")}
                  />
                ) : null}
              </div>
            ))
          )}
        </div>
      </Card>

      <Card className="border-slate-800 bg-slate-900/50">
        <CardHeader>
          <CardTitle className="text-base">Category → expense account</CardTitle>
        </CardHeader>
        <div className="space-y-4">
          {categories.map((cat) => (
            <div key={cat} className="grid gap-2 md:grid-cols-2 md:items-center">
              <p className="text-white">{cat}</p>
              <select
                className={selectClass}
                value={categoryMappingFor(cat)}
                onChange={(e) => saveCategoryMapping(cat, e.target.value)}
              >
                <option value="">Select QB expense account…</option>
                {expenseCoa.map((a) => (
                  <option key={a.qb_account_id} value={a.qb_account_id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </div>
          ))}

          <div className="border-t border-slate-800 pt-4">
            <p className="mb-2 text-sm text-slate-400">Add custom category mapping</p>
            <div className="grid gap-2 md:grid-cols-2">
              <input
                className={selectClass}
                placeholder="FinSight category"
                value={newCategory}
                onChange={(e) => setNewCategory(e.target.value)}
              />
              <select
                className={selectClass}
                value={newCategoryQb}
                onChange={(e) => setNewCategoryQb(e.target.value)}
              >
                <option value="">Select QB expense account…</option>
                {expenseCoa.map((a) => (
                  <option key={a.qb_account_id} value={a.qb_account_id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </div>
            <Button
              className="mt-2"
              size="sm"
              disabled={!newCategory || !newCategoryQb}
              onClick={() => {
                saveCategoryMapping(newCategory, newCategoryQb);
                setNewCategory("");
                setNewCategoryQb("");
              }}
            >
              Add mapping
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
