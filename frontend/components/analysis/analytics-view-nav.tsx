"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";

const VIEWS = [
  { id: "overview", label: "Overview" },
  { id: "spending", label: "Spending" },
  { id: "income", label: "Income" },
  { id: "transfers", label: "Transfers" },
  { id: "compare", label: "Compare" },
  { id: "insights", label: "Insights" },
] as const;

export type AnalyticsView = (typeof VIEWS)[number]["id"];

export function AnalyticsViewNav() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const current = (searchParams.get("view") as AnalyticsView) || "overview";

  return (
    <nav className="flex flex-wrap gap-1 rounded-lg border border-slate-800/60 bg-slate-950/40 p-1">
      {VIEWS.map((v) => {
        const params = new URLSearchParams(searchParams.toString());
        params.set("view", v.id);
        const href = `${pathname}?${params.toString()}`;
        const active = current === v.id;
        return (
          <Link
            key={v.id}
            href={href}
            className={cn(
              "shrink-0 rounded-md px-4 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-blue-600 text-white shadow-sm"
                : "text-slate-400 hover:bg-slate-800/80 hover:text-white"
            )}
          >
            {v.label}
          </Link>
        );
      })}
    </nav>
  );
}
