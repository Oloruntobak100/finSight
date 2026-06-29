"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { PageLoader } from "@/components/ui/page-loader";
import { ApiError } from "@/lib/api";
import {
  getReconciliationRun,
  transitionReconciliationRun,
  type ReconciliationRun,
  type RunStatus,
} from "@/lib/reconciliation";
import { formatCurrency } from "@/lib/utils";
import { ReconciliationRunNav } from "../run-nav";

export default function SignOffPage() {
  const params = useParams();
  const runId = String(params.id);
  const [run, setRun] = useState<ReconciliationRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRun(await getReconciliationRun(runId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load run");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function transition(target: RunStatus) {
    setActing(true);
    setError(null);
    setInfo(null);
    try {
      const { run: updated } = await transitionReconciliationRun(runId, target);
      setRun(updated);
      setInfo(`Status updated to ${target}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Transition failed");
    } finally {
      setActing(false);
    }
  }

  if (loading) return <PageLoader message="Loading sign-off…" />;

  const variance = run?.variance ?? run?.balance_proof?.variance ?? 0;
  const balanced = Math.abs(variance) <= 0.01;
  const status = run?.status ?? "DRAFT";

  return (
    <div className="page-enter space-y-4">
      <ReconciliationRunNav runId={runId} status={run?.status} />

      <div>
        <h1 className="text-xl font-bold text-white">Sign-off and Lock</h1>
        <p className="text-sm text-slate-500">Complete the reconciliation workflow for this period.</p>
      </div>

      {run?.self_approved && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          Self-approved: preparer and approver are the same user. A separate approver will be required when team roles
          are enabled.
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>
      )}
      {info && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
          {info}
        </div>
      )}

      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 space-y-2 text-sm">
        <p>
          <span className="text-slate-500">Period:</span> {run?.period_start} → {run?.period_end}
        </p>
        <p>
          <span className="text-slate-500">Variance:</span>{" "}
          <span className={balanced ? "text-emerald-400" : "text-amber-400"}>
            {formatCurrency(variance, run?.summary?.currency ?? "NGN")}
          </span>
        </p>
        <p>
          <span className="text-slate-500">Status:</span> {status}
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {status === "DRAFT" && (
          <Button disabled={acting} onClick={() => void transition("IN_REVIEW")}>
            Submit for review
          </Button>
        )}
        {status === "IN_REVIEW" && (
          <>
            <Button disabled={acting} onClick={() => void transition("ADJUSTED")}>
              Mark adjusted
            </Button>
            <Button variant="outline" disabled={acting} onClick={() => void transition("DRAFT")}>
              Return to draft
            </Button>
          </>
        )}
        {status === "ADJUSTED" && (
          <>
            <Button disabled={acting || !balanced} onClick={() => void transition("APPROVED")}>
              Approve reconciliation
            </Button>
            <Button variant="outline" disabled={acting} onClick={() => void transition("IN_REVIEW")}>
              Send back
            </Button>
          </>
        )}
        {status === "APPROVED" && (
          <Button disabled={acting} onClick={() => void transition("LOCKED")}>
            Lock period
          </Button>
        )}
        {status === "LOCKED" && (
          <span className="rounded bg-slate-800 px-3 py-2 text-sm text-slate-300">Period locked — no edits allowed</span>
        )}
      </div>
    </div>
  );
}
