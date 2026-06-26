"use client";

import { useEffect, useRef, useState } from "react";
import { Building2, Check, ChevronDown, Search, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AnalyticsMetaAccount } from "@/lib/analysis-filters";
import { cn } from "@/lib/utils";

interface AccountPickerProps {
  accounts: AnalyticsMetaAccount[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  providerFilter?: string;
}

export function AccountPicker({ accounts, selectedIds, onChange, providerFilter }: AccountPickerProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  const filtered =
    providerFilter && providerFilter !== ""
      ? accounts.filter((a) => a.provider === providerFilter)
      : accounts;

  const visible = filtered.filter((a) =>
    a.account_name.toLowerCase().includes(search.toLowerCase())
  );

  const grouped = visible.reduce<Record<string, AnalyticsMetaAccount[]>>((acc, a) => {
    const key = a.provider || "other";
    (acc[key] ??= []).push(a);
    return acc;
  }, {});

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  function toggle(id: string) {
    onChange(
      selectedIds.includes(id) ? selectedIds.filter((x) => x !== id) : [...selectedIds, id]
    );
  }

  function selectAll() {
    onChange(filtered.map((a) => a.id));
  }

  function clearAll() {
    onChange([]);
  }

  const label =
    selectedIds.length === 0
      ? "All accounts"
      : selectedIds.length === 1
        ? filtered.find((a) => a.id === selectedIds[0])?.account_name ?? "1 account"
        : `${selectedIds.length} accounts`;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex h-10 w-full min-w-0 items-center justify-between gap-2 rounded-lg border px-3 text-sm transition-colors",
          open
            ? "border-blue-500/60 bg-slate-900 ring-2 ring-blue-500/20"
            : "border-slate-700 bg-slate-900/80 hover:border-slate-600",
          selectedIds.length > 0 ? "text-white" : "text-slate-300"
        )}
      >
        <span className="flex items-center gap-2 truncate">
          <Building2 className="h-4 w-4 shrink-0 text-slate-500" />
          {label}
        </span>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-slate-500 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute left-0 z-50 mt-2 w-full max-w-sm rounded-xl border border-slate-700 bg-slate-950 p-3 shadow-2xl">
          <div className="relative mb-3">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search accounts…"
              className="h-9 pl-9 text-sm"
              autoFocus
            />
          </div>

          <div className="mb-2 flex gap-2">
            <Button type="button" variant="outline" size="sm" className="h-7 text-xs" onClick={selectAll}>
              Select all
            </Button>
            <Button type="button" variant="outline" size="sm" className="h-7 text-xs" onClick={clearAll}>
              Clear
            </Button>
          </div>

          <div className="max-h-64 space-y-3 overflow-y-auto pr-1">
            {filtered.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">
                No accounts found. Connect banks on the Accounts page.
              </p>
            ) : (
              Object.entries(grouped).map(([provider, list]) => (
                <div key={provider}>
                  <p className="mb-1.5 px-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    {provider}
                  </p>
                  <ul className="space-y-0.5">
                    {list.map((acc) => {
                      const checked = selectedIds.includes(acc.id);
                      return (
                        <li key={acc.id}>
                          <button
                            type="button"
                            onClick={() => toggle(acc.id)}
                            className={cn(
                              "flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left text-sm transition-colors",
                              checked ? "bg-blue-600/15 text-white" : "text-slate-300 hover:bg-slate-800"
                            )}
                          >
                            <span
                              className={cn(
                                "flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                                checked ? "border-blue-500 bg-blue-600" : "border-slate-600"
                              )}
                            >
                              {checked && <Check className="h-3 w-3 text-white" />}
                            </span>
                            <span className="flex-1 truncate">{acc.account_name}</span>
                            <Badge variant="secondary" className="text-[10px]">
                              {acc.currency}
                            </Badge>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))
            )}
          </div>

          {selectedIds.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1 border-t border-slate-800 pt-3">
              {selectedIds.map((id) => {
                const acc = accounts.find((a) => a.id === id);
                if (!acc) return null;
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => toggle(id)}
                    className="inline-flex items-center gap-1 rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-300 hover:bg-slate-700"
                  >
                    {acc.account_name}
                    <X className="h-3 w-3" />
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
