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
  getQuickBooksStatus,
  listCoa,
  listMappings,
  syncCoa,
  upsertMapping,
  type AccountMapping,
  type CoaAccount,
} from "@/lib/books";

interface BankAccount {
  id: string;
  account_name: string;
  provider: string;
}

const selectClass =
  "h-10 w-full rounded-md border border-slate-700 bg-slate-900 px-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500";

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

      const [coaRes, mapRes, meta] = await Promise.all([
        listCoa(),
        listMappings(),
        apiFetch<{ accounts: BankAccount[]; categories: string[] }>("/transactions/meta"),
      ]);
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
      setMessage(`Synced ${result.synced} accounts from QuickBooks`);
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

  function bankMappingFor(accountId: string): string {
    return mappings.find((m) => m.mapping_type === "bank_account" && m.finsight_key === accountId)
      ?.qb_account_id ?? "";
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
            <p className="text-sm text-slate-500">Connect a Plaid or Mono bank account first.</p>
          ) : (
            bankAccounts.map((bank) => (
              <div key={bank.id} className="grid gap-2 md:grid-cols-2 md:items-center">
                <div>
                  <p className="font-medium text-white">{bank.account_name}</p>
                  <p className="text-xs text-slate-500">{bank.provider}</p>
                </div>
                <select
                  className={selectClass}
                  value={bankMappingFor(bank.id)}
                  onChange={(e) => saveBankMapping(bank.id, e.target.value)}
                >
                  <option value="">Select QB bank account…</option>
                  {bankCoa.map((a) => (
                    <option key={a.qb_account_id} value={a.qb_account_id}>
                      {a.name}
                    </option>
                  ))}
                </select>
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
