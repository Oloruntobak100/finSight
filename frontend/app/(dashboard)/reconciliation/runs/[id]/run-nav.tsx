"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const STEPS = [
  { href: "matching", label: "Transaction Matching" },
  { href: "balance-proof", label: "Balance Proof" },
  { href: "journals", label: "Journal Entries" },
  { href: "sign-off", label: "Sign-off" },
  { href: "audit", label: "Audit Trail" },
] as const;

export function ReconciliationRunNav({ runId, status }: { runId: string; status?: string }) {
  const pathname = usePathname();
  const base = `/reconciliation/runs/${runId}`;

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 pb-3">
      <Link href="/reconciliation" className="text-xs text-slate-500 hover:text-slate-300">
        ← Setup
      </Link>
      {status && (
        <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">{status}</span>
      )}
      {STEPS.map((step) => {
        const href = `${base}/${step.href}`;
        const active = pathname.includes(step.href);
        return (
          <Link
            key={step.href}
            href={href}
            className={cn(
              "rounded-lg px-3 py-1.5 text-sm",
              active ? "bg-blue-600/20 text-blue-400" : "text-slate-400 hover:text-slate-200"
            )}
          >
            {step.label}
          </Link>
        );
      })}
    </div>
  );
}
