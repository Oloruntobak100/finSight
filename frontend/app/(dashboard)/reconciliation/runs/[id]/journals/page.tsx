"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { PageLoader } from "@/components/ui/page-loader";
import { listCoa, type CoaAccount } from "@/lib/books";
import { ApiError } from "@/lib/api";
import {
  createReconciliationAdjustment,
  listReconciliationAdjustments,
  postReconciliationJournal,
  type ReconciliationAdjustment,
} from "@/lib/reconciliation";
import { formatCurrency } from "@/lib/utils";
import { ReconciliationRunNav } from "../run-nav";

const selectClass =
  "mt-1 block w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-white";

export default function JournalsPage() {
  const params = useParams();
  const runId = String(params.id);
  const [adjustments, setAdjustments] = useState<ReconciliationAdjustment[]>([]);
  const [coa, setCoa] = useState<CoaAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [posting, setPosting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [adjType, setAdjType] = useState("BANK_CHARGE");
  const [amount, setAmount] = useState("");
  const [offsetId, setOffsetId] = useState("");
  const [description, setDescription] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [adj, coaRes] = await Promise.all([
        listReconciliationAdjustments(runId),
        listCoa(),
      ]);
      setAdjustments(adj.adjustments);
      setCoa(coaRes.items);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load journal entries");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  const expenseCoa = coa.filter((a) => ["Expense", "Other Expense", "Cost of Goods Sold"].includes(a.account_type ?? ""));
  const incomeCoa = coa.filter((a) => ["Income", "Other Income"].includes(a.account_type ?? ""));

  async function addAdjustment() {
    if (!amount || !offsetId) return;
    const acct = coa.find((a) => a.qb_account_id === offsetId);
    try {
      await createReconciliationAdjustment(runId, {
        adjustment_type: adjType,
        affects_side: "BOOK",
        amount: parseFloat(amount),
        description: description || undefined,
        offset_qb_account_id: offsetId,
        offset_qb_account_name: acct?.name,
        journal_entry_required: true,
      });
      setAmount("");
      setDescription("");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to create adjustment");
    }
  }

  async function postJournal(adjustmentId: string) {
    setPosting(adjustmentId);
    try {
      await postReconciliationJournal(runId, adjustmentId);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Post to QuickBooks failed");
    } finally {
      setPosting(null);
    }
  }

  if (loading) return <PageLoader message="Loading journal entries…" />;

  return (
    <div className="page-enter space-y-4">
      <ReconciliationRunNav runId={runId} />

      <div>
        <h1 className="text-xl font-bold text-white">Required Journal Entries</h1>
        <p className="text-sm text-slate-500">Post adjusting entries to QuickBooks before approval.</p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>
      )}

      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="mb-3 text-sm font-medium text-slate-300">Add adjustment</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm text-slate-400">
            Type
            <select value={adjType} onChange={(e) => setAdjType(e.target.value)} className={selectClass}>
              <option value="BANK_CHARGE">Bank charge</option>
              <option value="BANK_INTEREST">Bank interest</option>
              <option value="NSF_RETURN">NSF return</option>
              <option value="BOOK_ERROR">Book error</option>
            </select>
          </label>
          <label className="text-sm text-slate-400">
            Amount
            <input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} className={selectClass} />
          </label>
          <label className="text-sm text-slate-400 sm:col-span-2">
            Offset account
            <select value={offsetId} onChange={(e) => setOffsetId(e.target.value)} className={selectClass}>
              <option value="">Select COA account…</option>
              {(adjType === "BANK_INTEREST" ? incomeCoa : expenseCoa).map((a) => (
                <option key={a.qb_account_id} value={a.qb_account_id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm text-slate-400 sm:col-span-2">
            Description
            <input value={description} onChange={(e) => setDescription(e.target.value)} className={selectClass} />
          </label>
        </div>
        <Button className="mt-3" onClick={() => void addAdjustment()}>
          Queue journal entry
        </Button>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-800">
        <table className="table-fit w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-left text-slate-500">
              <th className="p-3">Type</th>
              <th className="p-3">Description</th>
              <th className="p-3 text-right">Amount</th>
              <th className="p-3">Status</th>
              <th className="p-3">Action</th>
            </tr>
          </thead>
          <tbody>
            {adjustments.length === 0 ? (
              <tr>
                <td colSpan={5} className="p-4 text-slate-500">
                  No journal entries queued.
                </td>
              </tr>
            ) : (
              adjustments.map((adj) => (
                <tr key={adj.id} className="border-b border-slate-800/50">
                  <td className="p-3">{adj.adjustment_type}</td>
                  <td className="p-3">{adj.description ?? adj.offset_qb_account_name ?? "—"}</td>
                  <td className="p-3 text-right">{formatCurrency(adj.amount, "NGN")}</td>
                  <td className="p-3">
                    {adj.journal_entry_posted ? (
                      <span className="text-emerald-400">Posted {adj.journal_entry_id}</span>
                    ) : (
                      <span className="text-amber-400">Pending</span>
                    )}
                  </td>
                  <td className="p-3">
                    {!adj.journal_entry_posted && adj.journal_entry_required && (
                      <Button
                        size="sm"
                        variant="outline"
                        loading={posting === adj.id}
                        onClick={() => void postJournal(adj.id)}
                      >
                        Post to QuickBooks
                      </Button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
