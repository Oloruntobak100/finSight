"use client";

import { Suspense } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { DateInput } from "@/components/ui/date-input";
import { buildBooksUrl, parseBooksDateRange } from "@/lib/books";

function BooksDateRangeInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { dateFrom, dateTo } = parseBooksDateRange(searchParams);
  const active = Boolean(dateFrom || dateTo);

  function pushDates(from: string, to: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (from) params.set("date_from", from);
    else params.delete("date_from");
    if (to) params.set("date_to", to);
    else params.delete("date_to");
    params.delete("page");
    const q = params.toString();
    router.push(q ? `${pathname}?${q}` : pathname);
  }

  function clearDates() {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("date_from");
    params.delete("date_to");
    params.delete("page");
    const q = params.toString();
    router.push(q ? `${pathname}?${q}` : pathname);
  }

  return (
    <div className="flex flex-wrap items-end justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="mb-1.5 block text-xs font-medium text-slate-400">Period from</label>
          <DateInput
            value={dateFrom}
            onChange={(e) => pushDates(e.target.value, dateTo)}
            className="w-[11rem]"
          />
        </div>
        <div>
          <label className="mb-1.5 block text-xs font-medium text-slate-400">Period to</label>
          <DateInput
            value={dateTo}
            onChange={(e) => pushDates(dateFrom, e.target.value)}
            className="w-[11rem]"
          />
        </div>
        {active && (
          <Button type="button" variant="ghost" size="sm" className="mb-0.5 text-slate-400" onClick={clearDates}>
            Clear period
          </Button>
        )}
      </div>
      <p className="max-w-md pb-1 text-xs text-slate-500">
        {active ? (
          <>
            Queue filtered to{" "}
            <span className="text-slate-300">
              {dateFrom || "…"} → {dateTo || "…"}
            </span>
          </>
        ) : (
          "Set a period to filter the Books queue by transaction date"
        )}
      </p>
    </div>
  );
}

export function BooksDateRange() {
  return (
    <Suspense fallback={null}>
      <BooksDateRangeInner />
    </Suspense>
  );
}
