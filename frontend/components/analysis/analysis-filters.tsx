"use client";

import { useState } from "react";
import { ChevronDown, Filter, SlidersHorizontal } from "lucide-react";
import { AccountPicker } from "@/components/analysis/account-picker";
import { Button } from "@/components/ui/button";
import { DateInput } from "@/components/ui/date-input";
import type {
  AnalysisFilterState,
  AnalyticsMetaAccount,
  ComparePeriod,
  DatePreset,
} from "@/lib/analysis-filters";
import { applyDatePreset } from "@/lib/analysis-filters";
import { cn } from "@/lib/utils";

interface AnalysisFiltersProps {
  filters: AnalysisFilterState;
  accounts: AnalyticsMetaAccount[];
  onChange: (filters: AnalysisFilterState) => void;
  onApply: () => void;
  loading?: boolean;
}

const selectClass =
  "h-10 w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500/40";

const DATE_PRESETS: { id: DatePreset; label: string }[] = [
  { id: "30d", label: "30d" },
  { id: "90d", label: "90d" },
  { id: "6m", label: "6 mo" },
  { id: "ytd", label: "YTD" },
];

export function AnalysisFiltersBar({
  filters,
  accounts,
  onChange,
  onApply,
  loading,
}: AnalysisFiltersProps) {
  const [advancedOpen, setAdvancedOpen] = useState(false);

  function setPreset(preset: DatePreset) {
    if (preset === "custom") return;
    onChange({ ...filters, ...applyDatePreset(preset) });
  }

  return (
    <div className="rounded-xl border border-slate-800/60 bg-slate-950/50">
      {/* Primary toolbar — visible essentials (REDUCE + ORGANIZE) */}
      <div className="flex flex-wrap items-end gap-3 p-4">
        <div className="flex flex-wrap gap-1.5">
          {DATE_PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setPreset(p.id)}
              className="rounded-md border border-slate-700/80 px-2.5 py-1.5 text-xs font-medium text-slate-400 transition-colors hover:border-slate-600 hover:text-white"
            >
              {p.label}
            </button>
          ))}
        </div>

        <div className="grid min-w-[130px] flex-1 gap-1">
          <label className="text-[10px] font-medium uppercase tracking-wide text-slate-500">From</label>
          <DateInput
            value={filters.dateFrom}
            onChange={(e) => onChange({ ...filters, dateFrom: e.target.value })}
            className="h-10"
          />
        </div>
        <div className="grid min-w-[130px] flex-1 gap-1">
          <label className="text-[10px] font-medium uppercase tracking-wide text-slate-500">To</label>
          <DateInput
            value={filters.dateTo}
            onChange={(e) => onChange({ ...filters, dateTo: e.target.value })}
            className="h-10"
          />
        </div>

        <div className="grid min-w-[180px] flex-1 gap-1">
          <label className="text-[10px] font-medium uppercase tracking-wide text-slate-500">Accounts</label>
          <AccountPicker
            accounts={accounts}
            selectedIds={filters.accountIds}
            providerFilter={filters.provider || undefined}
            onChange={(accountIds) => onChange({ ...filters, accountIds })}
          />
        </div>

        <div className="grid min-w-[120px] gap-1">
          <label className="text-[10px] font-medium uppercase tracking-wide text-slate-500">Provider</label>
          <select
            className={selectClass}
            value={filters.provider}
            onChange={(e) =>
              onChange({
                ...filters,
                provider: e.target.value as AnalysisFilterState["provider"],
                accountIds: [],
              })
            }
          >
            <option value="">All</option>
            <option value="plaid">Plaid</option>
            <option value="mono">Mono</option>
          </select>
        </div>

        <Button onClick={onApply} loading={loading} className="h-10 shrink-0 px-6">
          <Filter className="mr-1.5 h-4 w-4" />
          Apply
        </Button>
      </div>

      {/* Advanced — hidden until needed (HIDE) */}
      <div className="border-t border-slate-800/60">
        <button
          type="button"
          onClick={() => setAdvancedOpen((o) => !o)}
          className="flex w-full items-center justify-between px-4 py-2.5 text-xs text-slate-500 transition-colors hover:text-slate-300"
        >
          <span className="flex items-center gap-2">
            <SlidersHorizontal className="h-3.5 w-3.5" />
            Advanced comparison &amp; options
          </span>
          <ChevronDown className={cn("h-4 w-4 transition-transform", advancedOpen && "rotate-180")} />
        </button>

        {advancedOpen && (
          <div className="grid gap-4 border-t border-slate-800/40 px-4 pb-4 pt-3 md:grid-cols-2 lg:grid-cols-4">
            <div>
              <label className="mb-1.5 block text-[10px] font-medium uppercase tracking-wide text-slate-500">
                Compare period
              </label>
              <select
                className={selectClass}
                value={filters.comparePeriod}
                onChange={(e) =>
                  onChange({ ...filters, comparePeriod: e.target.value as ComparePeriod })
                }
              >
                <option value="previous_month">vs last month</option>
                <option value="previous_year">vs last year</option>
                <option value="previous_period">vs prior period</option>
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-[10px] font-medium uppercase tracking-wide text-slate-500">
                Compare account A
              </label>
              <select
                className={selectClass}
                value={filters.compareAccountA}
                onChange={(e) => onChange({ ...filters, compareAccountA: e.target.value })}
              >
                <option value="">None</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.account_name} ({a.provider})
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-[10px] font-medium uppercase tracking-wide text-slate-500">
                Compare account B
              </label>
              <select
                className={selectClass}
                value={filters.compareAccountB}
                onChange={(e) => onChange({ ...filters, compareAccountB: e.target.value })}
              >
                <option value="">None</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.account_name} ({a.provider})
                  </option>
                ))}
              </select>
            </div>
            <div className="flex items-end">
              <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-800/80 px-3 py-2.5 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={filters.includeTransfers}
                  onChange={(e) => onChange({ ...filters, includeTransfers: e.target.checked })}
                  className="rounded border-slate-600 bg-slate-900"
                />
                Include transfers in spend/income
              </label>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
