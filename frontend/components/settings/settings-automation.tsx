"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getAutomationSettings,
  getLearningProgress,
  updateAutomationSettings,
  type AutomationSettings,
  type LearningProgressItem,
} from "@/lib/books";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";

interface SettingsAutomationProps {
  email: string;
  fullName?: string | null;
  country?: string | null;
  currency?: string | null;
  plan?: string | null;
}

export function SettingsAutomation({ email, fullName, country, currency, plan }: SettingsAutomationProps) {
  const [automation, setAutomation] = useState<AutomationSettings | null>(null);
  const [learning, setLearning] = useState<LearningProgressItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [auto, prog] = await Promise.all([getAutomationSettings(), getLearningProgress()]);
      setAutomation(auto);
      setLearning(prog.items);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function save(patch: Partial<AutomationSettings>) {
    setSaving(true);
    setMessage(null);
    try {
      const updated = await updateAutomationSettings(patch);
      setAutomation(updated);
      setMessage("Settings saved");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
        </CardHeader>
        <dl className="space-y-3 px-6 pb-6 text-sm">
          <div className="flex justify-between">
            <dt className="text-slate-400">Email</dt>
            <dd className="text-white">{email}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-400">Name</dt>
            <dd className="text-white">{fullName || "—"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-400">Country</dt>
            <dd className="text-white">{country || "—"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-400">Currency</dt>
            <dd className="text-white">{currency || "USD"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-400">Plan</dt>
            <dd className="text-white capitalize">{plan || "free"}</dd>
          </div>
        </dl>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>AI &amp; Automation</CardTitle>
        </CardHeader>
        <div className="space-y-4 px-6 pb-6">
          {message && <p className="text-sm text-emerald-400">{message}</p>}
          <label className="flex items-center justify-between text-sm">
            <span className="text-slate-300">Enable auto-post when confidence is high enough</span>
            <input
              type="checkbox"
              checked={automation?.auto_approve_enabled ?? false}
              onChange={(e) => save({ auto_approve_enabled: e.target.checked })}
              disabled={saving}
            />
          </label>
          <label className="block text-sm text-slate-300">
            Confidence threshold: {((automation?.auto_approve_threshold ?? 0.9) * 100).toFixed(0)}%
            <input
              type="range"
              min={70}
              max={95}
              value={(automation?.auto_approve_threshold ?? 0.9) * 100}
              onChange={(e) =>
                setAutomation((a) =>
                  a ? { ...a, auto_approve_threshold: Number(e.target.value) / 100 } : a
                )
              }
              onMouseUp={() =>
                automation &&
                save({ auto_approve_threshold: automation.auto_approve_threshold })
              }
              onTouchEnd={() =>
                automation &&
                save({ auto_approve_threshold: automation.auto_approve_threshold })
              }
              className="mt-2 w-full"
            />
          </label>
          <p className="text-xs text-slate-500">
            When enabled, FinSight will auto-post transactions overnight when fingerprint confidence
            meets your threshold. You can review all postings in the Posted tab.
          </p>
        </div>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Learning progress</CardTitle>
        </CardHeader>
        <div className="overflow-hidden px-6 pb-6">
          {learning.length === 0 ? (
            <p className="text-sm text-slate-500">
              Approve transactions in Books to train the AI. Patterns will appear here.
            </p>
          ) : (
            <table className="table-fit text-sm">
              <thead>
                <tr className="text-left text-slate-500">
                  <th className="pb-2">Payee pattern</th>
                  <th className="pb-2">QB account</th>
                  <th className="pb-2">Trained</th>
                  <th className="pb-2">Confidence</th>
                  <th className="pb-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {learning.map((row) => (
                  <tr key={row.payee_pattern} className="border-t border-slate-800">
                    <td className="py-2 text-white">{row.payee_pattern}</td>
                    <td className="py-2">{row.account_name}</td>
                    <td className="py-2">{row.transaction_count}</td>
                    <td className="py-2">{(row.avg_confidence * 100).toFixed(0)}%</td>
                    <td className="py-2 text-slate-400">{row.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>
    </div>
  );
}
