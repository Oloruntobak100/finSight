"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { PageLoader } from "@/components/ui/page-loader";
import { ApiError } from "@/lib/api";
import { getReconciliationAudit, type AuditEntry } from "@/lib/reconciliation";
import { ReconciliationRunNav } from "../run-nav";

export default function AuditPage() {
  const params = useParams();
  const runId = String(params.id);
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getReconciliationAudit(runId);
      setEntries(res.entries);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load audit log");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <PageLoader message="Loading audit trail…" />;

  return (
    <div className="page-enter space-y-4">
      <ReconciliationRunNav runId={runId} />

      <div>
        <h1 className="text-xl font-bold text-white">Audit Trail</h1>
        <p className="text-sm text-slate-500">Immutable log of all actions on this reconciliation run.</p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>
      )}

      <div className="space-y-2">
        {entries.length === 0 ? (
          <p className="text-slate-500">No audit entries yet.</p>
        ) : (
          entries.map((entry) => (
            <div key={entry.id} className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3 text-sm">
              <div className="flex flex-wrap justify-between gap-2">
                <span className="font-medium text-white">{entry.action}</span>
                <span className="text-xs text-slate-500">{new Date(entry.created_at).toLocaleString()}</span>
              </div>
              {entry.comment && <p className="mt-1 text-slate-400">{entry.comment}</p>}
              {entry.after_state && (
                <pre className="mt-2 overflow-x-auto text-xs text-slate-500">
                  {JSON.stringify(entry.after_state, null, 2)}
                </pre>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
