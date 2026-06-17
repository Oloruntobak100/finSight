"use client";

import { Check, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export type ConnectionPhase = "exchanging" | "syncing" | "finishing";
export type ConnectionProvider = "mono" | "plaid";

const PROVIDER_LABELS: Record<ConnectionProvider, string> = {
  mono: "Mono",
  plaid: "Plaid",
};

const STEPS: { id: ConnectionPhase; label: string; detail: string }[] = [
  {
    id: "exchanging",
    label: "Securing connection",
    detail: "Verifying your bank link with our servers",
  },
  {
    id: "syncing",
    label: "Importing transactions",
    detail: "Pulling your latest account activity",
  },
  {
    id: "finishing",
    label: "Almost done",
    detail: "Refreshing your connected accounts",
  },
];

interface ConnectionProgressProps {
  provider: ConnectionProvider;
  phase: ConnectionPhase;
  institutionHint?: string;
}

export function ConnectionProgress({ provider, phase, institutionHint }: ConnectionProgressProps) {
  const currentIdx = STEPS.findIndex((s) => s.id === phase);

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/75 p-4 backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-labelledby="connection-progress-title"
      aria-busy="true"
    >
      <div className="w-full max-w-md animate-in fade-in zoom-in-95 rounded-2xl border border-slate-800/80 bg-slate-900/95 p-6 shadow-2xl shadow-blue-950/20 duration-300">
        <div className="mb-6 flex items-start gap-4">
          <div className="relative flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-blue-600/15 ring-1 ring-blue-500/30">
            <Loader2 className="h-6 w-6 animate-spin text-blue-400" />
            <span className="absolute inset-0 rounded-xl bg-blue-500/10 animate-pulse" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium uppercase tracking-wider text-blue-400">
              {PROVIDER_LABELS[provider]}
            </p>
            <h2 id="connection-progress-title" className="text-lg font-semibold text-white">
              Connecting your bank
            </h2>
            <p className="mt-1 text-sm text-slate-400">
              {institutionHint
                ? `Setting up ${institutionHint}…`
                : "This usually takes a few seconds."}
            </p>
          </div>
        </div>

        <ol className="space-y-3">
          {STEPS.map((step, idx) => {
            const done = idx < currentIdx;
            const active = idx === currentIdx;
            return (
              <li
                key={step.id}
                className={cn(
                  "flex items-start gap-3 rounded-xl border px-4 py-3 transition-all duration-300",
                  done && "border-green-900/40 bg-green-950/20",
                  active && "border-blue-500/40 bg-blue-950/25 shadow-sm shadow-blue-950/30",
                  !done && !active && "border-slate-800/60 bg-slate-950/40 opacity-50"
                )}
              >
                <span
                  className={cn(
                    "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold transition-colors",
                    done && "bg-green-600/20 text-green-400",
                    active && "bg-blue-600/20 text-blue-400",
                    !done && !active && "bg-slate-800 text-slate-500"
                  )}
                >
                  {done ? <Check className="h-3.5 w-3.5" /> : active ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : idx + 1}
                </span>
                <div className="min-w-0">
                  <p
                    className={cn(
                      "text-sm font-medium",
                      active ? "text-white" : done ? "text-green-300" : "text-slate-500"
                    )}
                  >
                    {step.label}
                  </p>
                  {active && <p className="mt-0.5 text-xs text-slate-400">{step.detail}</p>}
                </div>
              </li>
            );
          })}
        </ol>

        <div className="mt-5 h-1 overflow-hidden rounded-full bg-slate-800">
          <div
            className="h-full rounded-full bg-gradient-to-r from-blue-600 to-blue-400 transition-all duration-500 ease-out"
            style={{ width: `${((currentIdx + 1) / STEPS.length) * 100}%` }}
          />
        </div>
      </div>
    </div>
  );
}
