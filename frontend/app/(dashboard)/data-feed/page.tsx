"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { FlaskConical, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchFeedStatus, formatDailyTxRange, formatLiveFeedTimestamp, PERSONA_LABELS, type SyntheticFeedAccount } from "@/lib/data-feed";
import { apiFetch } from "@/lib/api";

export default function DataFeedPage() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [accounts, setAccounts] = useState<SyntheticFeedAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const dev = await apiFetch<{ synthetic_feed_enabled?: boolean }>("/banking/dev-info").catch(
          () => ({ synthetic_feed_enabled: false })
        );
        if (!dev.synthetic_feed_enabled) {
          setEnabled(false);
          setLoading(false);
          return;
        }
        const data = await fetchFeedStatus();
        setEnabled(data.enabled);
        setAccounts(data.accounts);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load data feed");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => {
      void fetchFeedStatus()
        .then((data) => setAccounts(data.accounts))
        .catch(() => undefined);
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [enabled]);

  if (loading) {
    return (
      <div className="page-enter space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (!enabled) {
    return (
      <div className="page-enter space-y-4">
        <h1 className="text-2xl font-bold text-white">Data Feed</h1>
        <p className="text-slate-400">
          Synthetic data feed is not enabled. Use Mono sandbox keys or set{" "}
          <code className="text-slate-300">ENABLE_SYNTHETIC_FEED=true</code> in the backend.
        </p>
      </div>
    );
  }

  return (
    <div className="page-enter space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <FlaskConical className="h-6 w-6 text-amber-400" />
          <h1 className="text-2xl font-bold text-white">Data Feed</h1>
          <Badge className="border-amber-500/30 bg-amber-950/40 text-amber-300">Testing</Badge>
        </div>
        <p className="mt-1 text-slate-400">
          Configure a persona and generate realistic synthetic transactions. Mono sandbox import is optional.
        </p>
      </div>

      <div className="rounded-lg border border-amber-900/40 bg-amber-950/20 px-4 py-3 text-sm text-amber-200/90">
        Synthetic feed assists Mono sandbox testing. Generated rows are tagged <strong>Synthetic</strong> in
        Transactions.
      </div>

      {error && (
        <p className="rounded-lg border border-red-900/50 bg-red-950/30 px-4 py-3 text-sm text-red-300">
          {error}
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Mono banks</CardTitle>
          <CardDescription>Select a connected bank to configure import, persona, and live feed</CardDescription>
        </CardHeader>
        {accounts.length === 0 ? (
          <p className="px-6 pb-6 text-slate-500">
            No Mono banks connected.{" "}
            <Link href="/accounts" className="text-blue-400 hover:underline">
              Connect one in Accounts
            </Link>
            .
          </p>
        ) : (
          <div className="space-y-2 px-6 pb-6">
            {accounts.map((acct) => (
              <Link
                key={acct.id}
                href={`/data-feed/${acct.id}`}
                className="flex items-center justify-between rounded-lg border border-slate-800 p-4 transition-colors hover:border-slate-600"
              >
                <div>
                  <p className="font-medium text-white">{acct.account_name}</p>
                  <p className="text-sm text-slate-400">
                    {acct.profile
                      ? `${PERSONA_LABELS[acct.profile.persona_type as keyof typeof PERSONA_LABELS] || acct.profile.persona_type} · ${formatDailyTxRange(acct.profile)}`
                      : "No persona configured"}
                    {acct.live_feed_enabled && (
                      <span className="ml-2 text-green-400">· Live feed on</span>
                    )}
                  </p>
                  {acct.live_feed_enabled && (
                    <p className="mt-1 text-xs text-slate-500">
                      Last drip: {formatLiveFeedTimestamp(acct.last_live_run_at)}
                      {acct.last_live_drip?.status === "failed" && acct.last_live_drip.error ? (
                        <span className="ml-2 text-red-400" title={acct.last_live_drip.error}>
                          · Last run failed
                        </span>
                      ) : acct.last_live_drip?.transactions_created ? (
                        <span className="ml-2 text-slate-500">
                          · +{acct.last_live_drip.transactions_created} txns
                        </span>
                      ) : null}
                      <span className="ml-2">· Next: {formatLiveFeedTimestamp(acct.next_live_run_at)}</span>
                    </p>
                  )}
                </div>
                <ChevronRight className="h-5 w-5 text-slate-500" />
              </Link>
            ))}
          </div>
        )}
      </Card>

      <Button variant="outline" asChild>
        <Link href="/accounts">Manage accounts</Link>
      </Button>
    </div>
  );
}
