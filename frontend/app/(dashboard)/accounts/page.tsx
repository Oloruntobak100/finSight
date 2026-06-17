"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { usePlaidLink } from "react-plaid-link";
import { ChevronRight, FlaskConical } from "lucide-react";
import {
  ConnectionProgress,
  type ConnectionPhase,
  type ConnectionProvider,
} from "@/components/accounts/connection-progress";
import { SimulateTransactionDialog } from "@/components/accounts/simulate-transaction-dialog";
import { QuickBooksConnectButton } from "@/components/accounts/quickbooks-connect-button";
import { useMonoConnect } from "@/hooks/use-mono-connect";
import { apiFetch, ApiError, BANKING_TIMEOUT_MS } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

interface Account {
  id: string;
  provider: string;
  account_name: string;
  status: string;
  last_synced_at: string | null;
}

export default function AccountsPage() {
  return (
    <Suspense fallback={<div className="page-enter p-6 text-slate-400">Loading accounts…</div>}>
      <AccountsPageContent />
    </Suspense>
  );
}

function AccountsPageContent() {
  const searchParams = useSearchParams();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [pageLoading, setPageLoading] = useState(true);
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [connectingPlaid, setConnectingPlaid] = useState(false);
  const [loading, setLoading] = useState(false);
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [isSandbox, setIsSandbox] = useState(false);
  const [isMonoSandbox, setIsMonoSandbox] = useState(false);
  const [monoPublicKey, setMonoPublicKey] = useState<string | null>(null);
  const [monoConfigured, setMonoConfigured] = useState(false);
  const [monoCustomer, setMonoCustomer] = useState<{ name: string; email: string } | null>(null);
  const [connectingMono, setConnectingMono] = useState(false);
  const [connectionFlow, setConnectionFlow] = useState<{
    provider: ConnectionProvider;
    phase: ConnectionPhase;
    institutionHint?: string;
  } | null>(null);
  const [simulateTarget, setSimulateTarget] = useState<Account | null>(null);
  const linkingInProgressRef = useRef(false);

  const loadAccounts = useCallback(async (options?: { quiet?: boolean }) => {
    try {
      const data = await apiFetch<{ accounts: Account[] }>("/oauth/accounts", {
        timeoutMs: options?.quiet ? 20_000 : BANKING_TIMEOUT_MS,
      });
      setAccounts(data.accounts);
      return true;
    } catch (err) {
      if (options?.quiet) return false;
      const message =
        err instanceof ApiError ? err.message : "Could not load accounts.";
      setError(message);
      return false;
    }
  }, []);

  useEffect(() => {
    const connected = searchParams.get("connected");
    const err = searchParams.get("error");
    if (connected === "quickbooks") {
      setSyncMessage("QuickBooks connected successfully.");
      setError(null);
      void loadAccounts();
    } else if (err) {
      setError(decodeURIComponent(err));
    }
  }, [searchParams, loadAccounts]);

  useEffect(() => {
    let active = true;
    setPageLoading(true);
    setError(null);

    loadAccounts().finally(() => {
      if (active) setPageLoading(false);
    });

    apiFetch<{ plaid_env: string; mono_env: string; mono_configured: boolean }>("/banking/dev-info")
      .then((info) => {
        if (active) {
          setIsSandbox(info.plaid_env === "sandbox");
          setIsMonoSandbox(info.mono_env === "sandbox");
          setMonoConfigured(info.mono_configured);
        }
      })
      .catch(() => {});

    apiFetch<{ public_key: string; configured: boolean }>("/banking/mono/config")
      .then((config) => {
        if (active) {
          setMonoPublicKey(config.public_key || null);
          setMonoConfigured(config.configured);
        }
      })
      .catch(() => {});

    const supabase = createClient();
    supabase.auth.getUser().then(async ({ data: { user } }) => {
      if (!active || !user?.email) return;
      const { data: profile } = await supabase
        .from("users")
        .select("full_name")
        .eq("id", user.id)
        .maybeSingle();
      setMonoCustomer({
        email: user.email,
        name: profile?.full_name || user.email.split("@")[0],
      });
    });

    return () => {
      active = false;
    };
  }, [loadAccounts]);

  async function startPlaid() {
    setConnectingPlaid(true);
    setError(null);
    try {
      const data = await apiFetch<{ link_token: string }>("/banking/plaid/link-token", {
        method: "POST",
      });
      setLinkToken(data.link_token);
    } catch {
      setError("Could not open Plaid. Please try again.");
      setConnectingPlaid(false);
    }
  }

  const finalizeBankConnection = useCallback(
    async (
      provider: ConnectionProvider,
      institutionHint?: string,
      accountId?: string
    ) => {
      setConnectionFlow({ provider, phase: "syncing", institutionHint });
      setError(null);

      try {
        try {
          const syncPath = accountId
            ? `/banking/sync?account_id=${encodeURIComponent(accountId)}`
            : "/banking/sync";
          await apiFetch(syncPath, { method: "POST", timeoutMs: BANKING_TIMEOUT_MS });
        } catch {
          // Account is connected even if first sync fails — user can hit Sync All
        }

        setConnectionFlow({ provider, phase: "finishing", institutionHint });
        await loadAccounts({ quiet: true });

        setSyncMessage(
          provider === "mono"
            ? "African bank connected successfully."
            : "Bank connected successfully."
        );
      } finally {
        setConnectionFlow(null);
        linkingInProgressRef.current = false;
        setConnectingPlaid(false);
        setConnectingMono(false);
      }
    },
    [loadAccounts]
  );

  const { open, ready } = usePlaidLink({
    token: linkToken,
    onSuccess: async (public_token, metadata) => {
      const institution = metadata.institution?.name ?? "Bank account";
      linkingInProgressRef.current = true;
      setConnectionFlow({ provider: "plaid", phase: "exchanging", institutionHint: institution });
      setConnectingPlaid(true);
      setError(null);
      try {
        const exchangeResult = await apiFetch<{ account: Account }>("/banking/plaid/exchange", {
          method: "POST",
          timeoutMs: BANKING_TIMEOUT_MS,
          body: JSON.stringify({
            public_token,
            account_name: institution,
          }),
        });
        await finalizeBankConnection("plaid", institution, exchangeResult.account?.id);
      } catch {
        setConnectionFlow(null);
        linkingInProgressRef.current = false;
        setConnectingPlaid(false);
        setError("Connected to Plaid but setup failed. Try Sync All.");
      } finally {
        setLinkToken(null);
      }
    },
    onExit: () => {
      if (!linkingInProgressRef.current) {
        setConnectingPlaid(false);
      }
      setLinkToken(null);
    },
  });

  useEffect(() => {
    if (linkToken && ready) open();
  }, [linkToken, ready, open]);

  const handleMonoSuccess = useCallback(
    async (code: string) => {
      linkingInProgressRef.current = true;
      setConnectionFlow({ provider: "mono", phase: "exchanging" });
      setConnectingMono(true);
      setError(null);
      try {
        const result = await apiFetch<{ account: Account }>("/banking/mono/connect", {
          method: "POST",
          timeoutMs: BANKING_TIMEOUT_MS,
          body: JSON.stringify({ code }),
        });
        await finalizeBankConnection("mono", result.account?.account_name, result.account?.id);
      } catch {
        setConnectionFlow(null);
        linkingInProgressRef.current = false;
        setConnectingMono(false);
        setError("Connected to Mono but setup failed. Try Sync All.");
      }
    },
    [finalizeBankConnection]
  );

  const { open: openMono, ready: monoReady } = useMonoConnect({
    publicKey: monoPublicKey,
    customer: monoCustomer,
    onSuccess: handleMonoSuccess,
    onClose: () => {
      if (!linkingInProgressRef.current) {
        setConnectingMono(false);
      }
    },
  });

  function startMono() {
    if (!monoConfigured) {
      setError("Mono is not configured. Add MONO_PUBLIC_KEY and MONO_SECRET_KEY to .env.");
      return;
    }
    if (!monoReady) {
      setError("Mono widget is still loading. Please try again.");
      return;
    }
    setConnectingMono(true);
    setError(null);
    openMono();
  }

  async function connectXero() {
    const data = await apiFetch<{ authorization_url: string }>("/oauth/xero/authorize");
    window.location.href = data.authorization_url;
  }

  const syncAll = useCallback(async (options?: { quiet?: boolean }) => {
    if (!options?.quiet) {
      setLoading(true);
      setSyncMessage(null);
    }
    setError(null);
    try {
      const result = await apiFetch<{
        synced_transactions: number;
        recurring_marked: number;
        errors?: { account_id: string; error: string }[];
        status?: string;
      }>("/banking/sync", { method: "POST", timeoutMs: BANKING_TIMEOUT_MS });
      await loadAccounts();
      if (result.errors?.length) {
        setSyncMessage(
          `Synced ${result.synced_transactions} transactions with ${result.errors.length} account warning(s).`
        );
      } else if (!options?.quiet) {
        setSyncMessage(`Synced ${result.synced_transactions} new transaction(s).`);
      }
    } catch {
      setError("Sync failed. Please try again.");
    } finally {
      if (!options?.quiet) {
        setLoading(false);
      }
    }
  }, [loadAccounts]);

  // Background sync every 15 min only — not on every page visit (was blocking UI).
  useEffect(() => {
    if (accounts.length === 0) return;
    const interval = setInterval(() => syncAll({ quiet: true }), 15 * 60 * 1000);
    return () => clearInterval(interval);
  }, [accounts.length, syncAll]);

  function handleSimulateComplete(result: { success: boolean; message: string; error?: string }) {
    if (result.success) {
      setSyncMessage(result.message);
      setError(null);
    } else {
      setError(result.error || result.message);
    }
    loadAccounts();
  }

  async function disconnect(provider: string, accountId: string) {
    setError(null);
    setDisconnectingId(accountId);
    try {
      await apiFetch(`/oauth/${provider}/disconnect?account_id=${accountId}`, { method: "DELETE" });
      await loadAccounts();
    } catch {
      setError("Failed to disconnect account. Please try again.");
    } finally {
      setDisconnectingId(null);
    }
  }

  return (
    <div className="page-enter space-y-6">
      {connectionFlow && (
        <ConnectionProgress
          provider={connectionFlow.provider}
          phase={connectionFlow.phase}
          institutionHint={connectionFlow.institutionHint}
        />
      )}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Connected Accounts</h1>
          <p className="text-slate-400">Link banks and accounting software</p>
        </div>
        <Button onClick={() => syncAll()} loading={loading} loadingLabel="Syncing…" variant="outline">
          Sync All
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Plaid</CardTitle>
            <CardDescription>US & UK banks</CardDescription>
          </CardHeader>
          <Button
            onClick={startPlaid}
            loading={connectingPlaid}
            loadingLabel="Opening Plaid…"
            className="w-full"
          >
            Connect Bank
          </Button>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">QuickBooks</CardTitle>
            <CardDescription>Accounting software</CardDescription>
          </CardHeader>
          <QuickBooksConnectButton variant="outline" className="w-full" />
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Xero</CardTitle>
            <CardDescription>Accounting software</CardDescription>
          </CardHeader>
          <Button onClick={connectXero} variant="outline" className="w-full">
            Connect Xero
          </Button>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Mono</CardTitle>
            <CardDescription>
              Nigeria &amp; Africa banks
              {isMonoSandbox && " · Sandbox"}
            </CardDescription>
          </CardHeader>
          <Button
            onClick={startMono}
            loading={connectingMono}
            loadingLabel="Opening Mono…"
            variant="outline"
            className="w-full"
            disabled={!monoConfigured}
          >
            Connect Bank
          </Button>
        </Card>
      </div>

      {syncMessage && (
        <p className="rounded-lg border border-green-900/50 bg-green-950/30 px-4 py-3 text-sm text-green-300">
          {syncMessage}
        </p>
      )}

      {error && (
        <p className="rounded-lg border border-red-900/50 bg-red-950/30 px-4 py-3 text-sm text-red-300">
          {error}
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Your Accounts</CardTitle>
        </CardHeader>
        {pageLoading ? (
          <div className="space-y-3">
            {[1, 2].map((i) => (
              <div key={i} className="flex items-center justify-between rounded-lg border border-slate-800 p-4">
                <div className="space-y-2">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-3 w-16" />
                </div>
                <Skeleton className="h-8 w-24" />
              </div>
            ))}
          </div>
        ) : accounts.length === 0 && !connectionFlow ? (
          <p className="text-slate-500">No accounts connected yet</p>
        ) : (
          <div className="space-y-3">
            {connectionFlow && (
              <div className="flex flex-col gap-3 rounded-lg border border-blue-500/30 bg-blue-950/20 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="space-y-2">
                  <Skeleton className="h-4 w-36 bg-blue-900/40" />
                  <Skeleton className="h-3 w-20 bg-blue-900/30" />
                </div>
                <Badge className="border-blue-500/30 bg-blue-950/50 text-blue-300">Connecting…</Badge>
              </div>
            )}
            {accounts.map((acc) => (
              <div
                key={acc.id}
                className="flex flex-col gap-3 rounded-lg border border-slate-800 transition-colors hover:border-slate-700 sm:flex-row sm:items-center sm:justify-between"
              >
                <Link
                  href={`/transactions?account_id=${encodeURIComponent(acc.id)}`}
                  className="group flex flex-1 items-center gap-3 p-4 sm:pr-2"
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-white group-hover:text-blue-300">{acc.account_name}</p>
                    <p className="text-sm capitalize text-slate-400">{acc.provider}</p>
                    <p className="mt-1 text-xs text-slate-600 group-hover:text-slate-500">View transactions</p>
                  </div>
                  <ChevronRight className="h-5 w-5 shrink-0 text-slate-600 transition-transform group-hover:translate-x-0.5 group-hover:text-blue-400" />
                </Link>
                <div className="flex flex-wrap items-center gap-2 border-t border-slate-800/80 px-4 pb-4 sm:border-t-0 sm:px-4 sm:pb-4 sm:pl-0">
                  <Badge variant={acc.status === "active" ? "success" : "warning"}>{acc.status}</Badge>
                  {acc.last_synced_at && (
                    <span className="text-xs text-slate-500">Synced {acc.last_synced_at}</span>
                  )}
                  {isSandbox && acc.provider === "plaid" && (
                    <Button variant="outline" size="sm" onClick={() => setSimulateTarget(acc)}>
                      <FlaskConical className="h-3.5 w-3.5" />
                      Add test txn
                    </Button>
                  )}
                  <Button
                    variant="destructive"
                    size="sm"
                    loading={disconnectingId === acc.id}
                    loadingLabel="Disconnecting…"
                    onClick={() => disconnect(acc.provider, acc.id)}
                  >
                    Disconnect
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {simulateTarget && (
        <SimulateTransactionDialog
          key={simulateTarget.id}
          open={!!simulateTarget}
          onOpenChange={(open) => !open && setSimulateTarget(null)}
          accountId={simulateTarget.id}
          accountName={simulateTarget.account_name}
          onComplete={handleSimulateComplete}
        />
      )}
    </div>
  );
}
