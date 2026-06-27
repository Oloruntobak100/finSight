"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ArrowLeft, FlaskConical } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DateInput } from "@/components/ui/date-input";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiFetch } from "@/lib/api";
import {
  datePresetMonths,
  fetchAccountDetail,
  fillHistory,
  importMonoHistory,
  pauseLiveFeed,
  PERSONA_LABELS,
  runLiveDripNow,
  saveProfile,
  startLiveFeed,
  type PersonaType,
  type SyntheticFeedProfile,
  type SyntheticFeedRun,
} from "@/lib/data-feed";

const selectClass =
  "h-10 w-full rounded-md border border-slate-700 bg-slate-900 px-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500";

const PERSONA_TYPES: PersonaType[] = ["individual", "freelancer", "small_business", "retail"];

export default function DataFeedAccountPage() {
  const params = useParams();
  const accountId = params.accountId as string;

  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<SyntheticFeedProfile | null>(null);
  const [runs, setRuns] = useState<SyntheticFeedRun[]>([]);
  const [presets, setPresets] = useState<Record<string, Record<string, unknown>>>({});

  const [personaType, setPersonaType] = useState<PersonaType>("individual");
  const [dailyTxMin, setDailyTxMin] = useState(8);
  const [dailyTxMax, setDailyTxMax] = useState(20);
  const [remarkRate, setRemarkRate] = useState(0.25);
  const [liveIntervalHours, setLiveIntervalHours] = useState(6);
  const [autoClassify, setAutoClassify] = useState(true);

  const [histStart, setHistStart] = useState("");
  const [histEnd, setHistEnd] = useState("");
  const [fillStart, setFillStart] = useState("");
  const [fillEnd, setFillEnd] = useState("");
  const [fillCount, setFillCount] = useState("");
  const [isMonoSandbox, setIsMonoSandbox] = useState(true);
  const [showMonoImport, setShowMonoImport] = useState(false);

  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const dev = await apiFetch<{ mono_env?: string }>("/banking/dev-info").catch(
        (): { mono_env?: string } => ({})
      );
      const sandbox = dev.mono_env === "sandbox";
      setIsMonoSandbox(sandbox);
      setShowMonoImport(!sandbox);

      const data = await fetchAccountDetail(accountId);
      setProfile(data.profile);
      setRuns(data.runs);
      setPresets(data.presets);
      const p = data.profile;
      setPersonaType(p.persona_type as PersonaType);
      setDailyTxMin(p.daily_tx_min ?? Math.max(1, p.daily_tx_target - 7));
      setDailyTxMax(p.daily_tx_max ?? Math.min(500, p.daily_tx_target + 7));
      setLiveIntervalHours(p.live_interval_hours);
      setAutoClassify(p.auto_classify);
      const cfg = p.persona_config as { remark_rate?: number };
      if (cfg.remark_rate != null) setRemarkRate(cfg.remark_rate);
      if (p.historical_start) setHistStart(String(p.historical_start).slice(0, 10));
      if (p.historical_end) setHistEnd(String(p.historical_end).slice(0, 10));
      const preset = datePresetMonths(6);
      setFillStart(preset.start);
      setFillEnd(preset.end);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to load";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  function applyPreset(type: PersonaType) {
    setPersonaType(type);
    const preset = presets[type];
    if (preset && typeof preset.daily_tx_min === "number" && typeof preset.daily_tx_max === "number") {
      setDailyTxMin(preset.daily_tx_min);
      setDailyTxMax(preset.daily_tx_max);
    }
    if (preset && typeof preset.remark_rate === "number") {
      setRemarkRate(preset.remark_rate);
    }
  }

  async function persistProfile() {
    const res = await saveProfile(accountId, {
      persona_type: personaType,
      persona_config: { remark_rate: remarkRate },
      daily_tx_min: dailyTxMin,
      daily_tx_max: dailyTxMax,
      live_interval_hours: liveIntervalHours,
      auto_classify: autoClassify,
      historical_start: histStart || undefined,
      historical_end: histEnd || undefined,
    });
    setProfile(res.profile);
    return res.profile;
  }

  async function handleSaveProfile() {
    setBusy("save");
    setError(null);
    try {
      await persistProfile();
      setMessage("Persona saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleImportMono() {
    if (!histStart || !histEnd) {
      setError("Set historical start and end dates.");
      return;
    }
    setBusy("import");
    setError(null);
    try {
      const res = await importMonoHistory(accountId, histStart, histEnd);
      setMessage(`Imported ${res.imported} transaction(s) from Mono.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleFillHistory() {
    if (!fillStart || !fillEnd) {
      setError("Set fill history date range.");
      return;
    }
    setBusy("fill");
    setError(null);
    setMessage(null);
    try {
      await persistProfile();
      const count = fillCount ? parseInt(fillCount, 10) : undefined;
      const res = await fillHistory(accountId, fillStart, fillEnd, count);
      setMessage(
        `Generated ${res.created} synthetic transaction(s). Classified ${res.classified}. Open Transactions and filter by Synthetic to view them.`
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fill failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleStartLive() {
    setBusy("live-start");
    setError(null);
    try {
      await persistProfile();
      const res = await startLiveFeed(accountId);
      setProfile(res.profile);
      setMessage("Live feed started.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start live feed");
    } finally {
      setBusy(null);
    }
  }

  async function handlePauseLive() {
    setBusy("live-pause");
    try {
      const res = await pauseLiveFeed(accountId);
      setProfile(res.profile);
      setMessage("Live feed paused.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not pause");
    } finally {
      setBusy(null);
    }
  }

  async function handleRunNow() {
    setBusy("run-now");
    try {
      const res = await runLiveDripNow(accountId);
      setMessage(`Drip: ${res.created} new transaction(s).`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Drip failed");
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return (
      <div className="page-enter space-y-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  return (
    <div className="page-enter space-y-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" asChild>
          <Link href="/data-feed">
            <ArrowLeft className="mr-1 h-4 w-4" />
            Back
          </Link>
        </Button>
        <FlaskConical className="h-5 w-5 text-amber-400" />
        <h1 className="text-xl font-bold text-white">Configure data feed</h1>
        {profile?.live_feed_enabled && (
          <Badge className="border-green-500/30 bg-green-950/40 text-green-300">Live</Badge>
        )}
      </div>

      {message && (
        <p className="rounded-lg border border-green-900/50 bg-green-950/30 px-4 py-3 text-sm text-green-300">
          {message}
        </p>
      )}
      {error && (
        <div className="rounded-lg border border-red-900/50 bg-red-950/30 px-4 py-3 text-sm text-red-300">
          <p>{error}</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={() => void load()}>
            Retry
          </Button>
        </div>
      )}

      <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3 text-sm text-slate-400">
        <p className="font-medium text-slate-300">Recommended workflow (Mono sandbox)</p>
        <ol className="mt-2 list-inside list-decimal space-y-1">
          <li>
            <strong className="text-slate-300">Persona</strong> — pick account type, daily volume range, remark rate.
          </li>
          <li>
            <strong className="text-slate-300">Fill history</strong> — generate realistic synthetic transactions spread
            across past dates (main data source in sandbox).
          </li>
          <li>
            <strong className="text-slate-300">Live feed</strong> — drip new synthetic transactions going forward.
          </li>
          <li>
            <strong className="text-slate-300">Mono import (optional)</strong> — only if you want whatever Mono returns;
            often the same rows regardless of date range.
          </li>
        </ol>
      </div>

      {isMonoSandbox && (
        <div className="rounded-lg border border-amber-900/40 bg-amber-950/20 px-4 py-3 text-sm text-amber-200/90">
          Mono sandbox history is usually thin and repetitive (same names, clustered dates). Skip Mono import — use{" "}
          <strong>Fill history</strong> after saving a persona.
        </div>
      )}

      {/* Persona */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">1. Persona</CardTitle>
          <CardDescription>
            Start here. Defines transaction types (transfers, POS, airtime, fees), daily volume range, and how often
            narrations include a user remark (most Nigerian transfers have none).
          </CardDescription>
        </CardHeader>
        <div className="space-y-4 px-6 pb-6">
          <div className="flex flex-wrap gap-2">
            {PERSONA_TYPES.map((t) => (
              <Button
                key={t}
                variant={personaType === t ? "default" : "outline"}
                size="sm"
                onClick={() => applyPreset(t)}
              >
                {PERSONA_LABELS[t]}
              </Button>
            ))}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-xs text-slate-400">Daily transactions (min)</label>
              <Input
                type="number"
                min={1}
                max={500}
                value={dailyTxMin}
                onChange={(e) => setDailyTxMin(parseInt(e.target.value, 10) || 1)}
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs text-slate-400">Daily transactions (max)</label>
              <Input
                type="number"
                min={1}
                max={500}
                value={dailyTxMax}
                onChange={(e) => setDailyTxMax(parseInt(e.target.value, 10) || 1)}
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs text-slate-400">Live feed interval (hours)</label>
              <select
                className={selectClass}
                value={liveIntervalHours}
                onChange={(e) => setLiveIntervalHours(parseInt(e.target.value, 10))}
              >
                <option value={6}>Every 6 hours</option>
                <option value={12}>Every 12 hours</option>
                <option value={24}>Daily</option>
              </select>
            </div>
          </div>
          <div>
            <label className="mb-1.5 block text-xs text-slate-400">
              Remark rate ({Math.round(remarkRate * 100)}% of transfers include a user description)
            </label>
            <input
              type="range"
              min={0}
              max={100}
              value={Math.round(remarkRate * 100)}
              onChange={(e) => setRemarkRate(parseInt(e.target.value, 10) / 100)}
              className="w-full accent-blue-500"
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={autoClassify}
              onChange={(e) => setAutoClassify(e.target.checked)}
              className="rounded border-slate-600 bg-slate-900"
            />
            Auto-classify new transactions for Books
          </label>
          <Button onClick={handleSaveProfile} loading={busy === "save"} variant="outline">
            Save persona
          </Button>
        </div>
      </Card>

      {/* Fill history */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">2. Fill history</CardTitle>
          <CardDescription>
            Generates Nigeria-realistic synthetic transactions across a past date range — tagged Synthetic in
            Transactions. Spread across dates so Reports and filters behave realistically. Recommended as your first data
            step in Mono sandbox.
          </CardDescription>
        </CardHeader>
        <div className="space-y-4 px-6 pb-6">
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label className="mb-1.5 block text-xs text-slate-400">Start</label>
              <DateInput value={fillStart} onChange={(e) => setFillStart(e.target.value)} />
            </div>
            <div>
              <label className="mb-1.5 block text-xs text-slate-400">End</label>
              <DateInput value={fillEnd} onChange={(e) => setFillEnd(e.target.value)} />
            </div>
            <div>
              <label className="mb-1.5 block text-xs text-slate-400">Count (optional)</label>
              <Input
                placeholder="Auto"
                value={fillCount}
                onChange={(e) => setFillCount(e.target.value)}
              />
            </div>
          </div>
          <Button
            onClick={handleFillHistory}
            loading={busy === "fill"}
            loadingLabel="Generating history…"
          >
            Fill history
          </Button>
          <p className="text-xs text-slate-500">
            Saves your persona, then generates transactions on the server. Large ranges can take up to a minute — keep
            this page open until you see a success message.
          </p>
        </div>
      </Card>

      {/* Live feed */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">3. Live feed</CardTitle>
          <CardDescription>
            Adds a small batch of new synthetic transactions on a timer (not a full backfill). Keeps the account
            feeling active for Books, Reports, and date filters.
          </CardDescription>
        </CardHeader>
        <div className="flex flex-wrap gap-2 px-6 pb-2">
          <p className="w-full text-xs text-slate-500">
            ~{Math.max(1, Math.round((dailyTxMin + dailyTxMax) / 2 / Math.max(1, 24 / liveIntervalHours)))}{" "}
            transactions every {liveIntervalHours}h ({dailyTxMin}–{dailyTxMax}/day range)
          </p>
        </div>
        <div className="flex flex-wrap gap-2 px-6 pb-6">
          {!profile?.live_feed_enabled ? (
            <Button onClick={handleStartLive} loading={busy === "live-start"}>
              Start live feed
            </Button>
          ) : (
            <Button onClick={handlePauseLive} variant="outline" loading={busy === "live-pause"}>
              Pause live feed
            </Button>
          )}
          <Button onClick={handleRunNow} variant="outline" loading={busy === "run-now"}>
            Run drip now
          </Button>
          {profile?.next_live_run_at && (
            <span className="self-center text-xs text-slate-500">
              Next run: {new Date(profile.next_live_run_at).toLocaleString()}
            </span>
          )}
        </div>
      </Card>

      {/* Optional Mono import */}
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
          <div>
            <CardTitle className="text-base">Optional: Mono historical import</CardTitle>
            <CardDescription>
              Pulls whatever Mono has for a date range. In sandbox this is often the same few transactions (or none)
              regardless of 3, 6, or 12 months — skip unless you specifically need real Mono-shaped rows mixed in.
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => setShowMonoImport((v) => !v)}>
            {showMonoImport ? "Hide" : "Show"}
          </Button>
        </CardHeader>
        {showMonoImport && (
          <div className="space-y-4 px-6 pb-6">
            <div className="flex flex-wrap gap-2">
              {[3, 6, 12].map((m) => {
                const p = datePresetMonths(m);
                return (
                  <Button
                    key={m}
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setHistStart(p.start);
                      setHistEnd(p.end);
                    }}
                  >
                    Last {m} months
                  </Button>
                );
              })}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="mb-1.5 block text-xs text-slate-400">Start</label>
                <DateInput value={histStart} onChange={(e) => setHistStart(e.target.value)} />
              </div>
              <div>
                <label className="mb-1.5 block text-xs text-slate-400">End</label>
                <DateInput value={histEnd} onChange={(e) => setHistEnd(e.target.value)} />
              </div>
            </div>
            <Button onClick={handleImportMono} loading={busy === "import"} loadingLabel="Importing…">
              Import from Mono
            </Button>
          </div>
        )}
      </Card>

      {/* Run log */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Run log</CardTitle>
          <CardDescription>History of Mono imports, history fills, and live drips for this bank account.</CardDescription>
        </CardHeader>
        <div className="overflow-x-auto px-6 pb-6">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-slate-400">
                <th className="pb-2 pr-4">Type</th>
                <th className="pb-2 pr-4">Created</th>
                <th className="pb-2 pr-4">Status</th>
                <th className="pb-2">When</th>
              </tr>
            </thead>
            <tbody>
              {runs.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-4 text-slate-500">
                    No runs yet
                  </td>
                </tr>
              ) : (
                runs.map((run) => (
                  <tr key={run.id} className="border-b border-slate-800/50">
                    <td className="py-2 pr-4 capitalize text-slate-300">{run.run_type.replace("_", " ")}</td>
                    <td className="py-2 pr-4 text-slate-400">{run.transactions_created}</td>
                    <td className="py-2 pr-4">
                      <Badge variant={run.status === "completed" ? "success" : run.status === "failed" ? "destructive" : "secondary"}>
                        {run.status}
                      </Badge>
                    </td>
                    <td className="py-2 text-xs text-slate-500">
                      {new Date(run.started_at).toLocaleString()}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
