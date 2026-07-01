"use client";

import { useMemo, useState } from "react";
import { ArrowDownLeft, ArrowUpRight, FlaskConical } from "lucide-react";
import { apiFetch, ApiError } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

type TxnType = "expense" | "income";

interface Preset {
  id: string;
  label: string;
  description: string;
  amount: number;
  type: TxnType;
}

const PRESETS: Preset[] = [
  { id: "coffee", label: "Coffee", description: "Starbucks", amount: 4.75, type: "expense" },
  { id: "subscription", label: "Subscription", description: "Netflix", amount: 15.99, type: "expense" },
  { id: "groceries", label: "Groceries", description: "Whole Foods", amount: 62.4, type: "expense" },
  { id: "paycheck", label: "Paycheck", description: "Salary Deposit", amount: 2500, type: "income" },
];

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  accountId: string;
  accountName: string;
  onComplete: (result: {
    success: boolean;
    message: string;
    error?: string;
    syncedTransactions?: number;
  }) => void;
}

export function SimulateTransactionDialog({
  open,
  onOpenChange,
  accountId,
  accountName,
  onComplete,
}: Props) {
  const [txnType, setTxnType] = useState<TxnType>("expense");
  const [presetId, setPresetId] = useState("coffee");
  const [customDescription, setCustomDescription] = useState("");
  const [customAmount, setCustomAmount] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const isCustom = presetId === "custom";
  const activePreset = PRESETS.find((p) => p.id === presetId);

  const description = isCustom ? customDescription.trim() : activePreset?.description ?? "";
  const amount = isCustom ? parseFloat(customAmount) : activePreset?.amount ?? 0;

  const visiblePresets = PRESETS.filter((p) => p.type === txnType);

  const preview = useMemo(() => {
    if (!description || !amount || amount <= 0) return null;
    const sign = txnType === "income" ? "+" : "−";
    return `${sign}${formatCurrency(amount)} · ${description}`;
  }, [amount, description, txnType]);

  function selectType(type: TxnType) {
    setTxnType(type);
    const first = PRESETS.find((p) => p.type === type);
    if (first) setPresetId(first.id);
  }

  async function handleSubmit() {
    if (!description || !amount || amount <= 0) return;
    setSubmitting(true);
    try {
      const result = await apiFetch<{
        injected: boolean;
        synced_transactions: number;
        used_local_fallback?: boolean;
        note: string;
        inject_error?: string;
        sync_error?: string;
      }>("/banking/sandbox/simulate-purchase", {
        method: "POST",
        body: JSON.stringify({
          account_id: accountId,
          description,
          amount,
          transaction_type: txnType,
        }),
      });

      if (result.inject_error || result.sync_error) {
        onComplete({
          success: false,
          message: result.note,
          error: result.inject_error || result.sync_error,
        });
      } else {
        const synced = result.synced_transactions ?? 0;
        onComplete({
          success: true,
          syncedTransactions: synced,
          message:
            synced > 0
              ? `Added ${description} to ${accountName}. Check Transactions to see it.`
              : `Added to bank — still syncing. Open Transactions or tap Sync All.`,
        });
        onOpenChange(false);
      }
    } catch (err) {
      onComplete({
        success: false,
        message: "Could not add test transaction.",
        error: err instanceof ApiError ? String(err.message) : undefined,
      });
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit = description.length > 0 && amount > 0 && !submitting;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <div className="flex items-center gap-2 text-amber-400/90">
            <FlaskConical className="h-4 w-4" />
            <span className="text-xs font-medium uppercase tracking-wide">Sandbox only</span>
          </div>
          <DialogTitle>Add test transaction</DialogTitle>
          <DialogDescription>
            Inject mock data into <span className="text-slate-300">{accountName}</span> — not real
            money.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          {/* Type — one decision, two choices */}
          <div className="grid grid-cols-2 gap-2 rounded-lg bg-slate-900/60 p-1">
            <button
              type="button"
              onClick={() => selectType("expense")}
              className={`flex items-center justify-center gap-2 rounded-md px-3 py-2.5 text-sm font-medium transition-colors ${
                txnType === "expense"
                  ? "bg-slate-800 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <ArrowUpRight className="h-4 w-4 text-slate-400" />
              Expense
            </button>
            <button
              type="button"
              onClick={() => selectType("income")}
              className={`flex items-center justify-center gap-2 rounded-md px-3 py-2.5 text-sm font-medium transition-colors ${
                txnType === "income"
                  ? "bg-emerald-950/80 text-emerald-300 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <ArrowDownLeft className="h-4 w-4 text-emerald-500/80" />
              Income
            </button>
          </div>

          {/* Presets — reduce typing */}
          <div>
            <p className="mb-2 text-xs text-slate-500">Quick pick</p>
            <div className="flex flex-wrap gap-2">
              {visiblePresets.map((preset) => (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => setPresetId(preset.id)}
                  className={`rounded-full border px-3 py-1.5 text-sm transition-colors ${
                    presetId === preset.id
                      ? "border-blue-500/60 bg-blue-500/15 text-blue-300"
                      : "border-slate-700 text-slate-400 hover:border-slate-600 hover:text-slate-200"
                  }`}
                >
                  {preset.label}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setPresetId("custom")}
                className={`rounded-full border px-3 py-1.5 text-sm transition-colors ${
                  isCustom
                    ? "border-blue-500/60 bg-blue-500/15 text-blue-300"
                    : "border-slate-700 text-slate-400 hover:border-slate-600 hover:text-slate-200"
                }`}
              >
                Custom
              </button>
            </div>
          </div>

          {/* Custom — only when needed (Maeda: hide complexity) */}
          {isCustom && (
            <div className="grid gap-3 rounded-lg border border-slate-800 bg-slate-900/40 p-3">
              <div>
                <label className="mb-1.5 block text-xs text-slate-400">Merchant</label>
                <Input
                  placeholder="e.g. Uber, Rent, Bonus"
                  value={customDescription}
                  onChange={(e) => setCustomDescription(e.target.value)}
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs text-slate-400">Amount</label>
                <Input
                  type="number"
                  min="0.01"
                  step="0.01"
                  placeholder="0.00"
                  value={customAmount}
                  onChange={(e) => setCustomAmount(e.target.value)}
                />
              </div>
            </div>
          )}

          {/* Preview — trust through clarity */}
          {preview && (
            <div
              className={`rounded-lg border px-4 py-3 text-center text-sm font-medium ${
                txnType === "income"
                  ? "border-emerald-900/50 bg-emerald-950/30 text-emerald-300"
                  : "border-slate-800 bg-slate-900/50 text-white"
              }`}
            >
              {preview}
            </div>
          )}

          <Button
            className="w-full"
            disabled={!canSubmit}
            loading={submitting}
            loadingLabel="Adding…"
            onClick={handleSubmit}
          >
            Add transaction
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
