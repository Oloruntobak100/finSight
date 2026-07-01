"use client";

import { useCallback, useEffect, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { apiFetch } from "@/lib/api";
import {
  buildAnalysisQueryString,
  getDefaultAnalysisFilters,
  loadAnalysisFilters,
  saveAnalysisFilters,
  type AnalysisFilterState,
  type AnalyticsMetaAccount,
} from "@/lib/analysis-filters";
import { AnalysisFiltersBar } from "@/components/analysis/analysis-filters";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { formatCurrency } from "@/lib/utils";

interface Forecast {
  horizon_days: number;
  predicted_income: number;
  predicted_expenses: number;
  projected_balance: number;
  confidence_score: number | null;
  confidence_low?: number | null;
  confidence_high?: number | null;
  currency?: string;
  data_source?: string;
}

export default function ForecastPage() {
  const [filters, setFilters] = useState(getDefaultAnalysisFilters);
  const [accounts, setAccounts] = useState<AnalyticsMetaAccount[]>([]);
  const [forecasts, setForecasts] = useState<Forecast[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setFilters(loadAnalysisFilters());
    Promise.all([
      apiFetch<{ accounts: AnalyticsMetaAccount[] }>("/analytics/meta").catch(() => ({ accounts: [] })),
      apiFetch<{ accounts: Array<{ id: string; account_name: string; provider: string }> }>(
        "/oauth/accounts"
      ).catch(() => ({ accounts: [] })),
    ]).then(([meta, oauth]) => {
      const fromMeta = meta.accounts ?? [];
      if (fromMeta.length > 0) {
        setAccounts(fromMeta);
        return;
      }
      setAccounts(
        (oauth.accounts ?? []).map((a) => ({
          id: a.id,
          account_name: a.account_name,
          provider: a.provider,
          currency: "USD",
        }))
      );
    });
  }, []);

  const load = useCallback(async (f: AnalysisFilterState) => {
    setLoading(true);
    try {
      const qs = buildAnalysisQueryString(f);
      const data = await apiFetch<Forecast[]>(`/analytics/forecast?${qs}`);
      setForecasts(data);
    } catch {
      setForecasts([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(filters);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function applyFilters() {
    saveAnalysisFilters(filters);
    load(filters);
  }

  const currency = forecasts[0]?.currency || "USD";
  const forecastSource = forecasts[0]?.data_source === "quickbooks" ? "QuickBooks P&L history" : "Bank transactions";
  const chartData = forecasts.map((f) => ({
    name: `${f.horizon_days}d`,
    balance: f.projected_balance,
    low: f.confidence_low ?? f.projected_balance * 0.9,
    high: f.confidence_high ?? f.projected_balance * 1.1,
  }));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Forecast</h1>
        <p className="text-slate-400">
          30 / 60 / 90-day projections · {forecastSource}
        </p>
      </div>

      <AnalysisFiltersBar
        filters={filters}
        accounts={accounts}
        onChange={setFilters}
        onApply={applyFilters}
      />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Projected balance ({currency})</CardTitle>
          <Button variant="outline" size="sm" onClick={() => load(filters)} disabled={loading}>
            Regenerate
          </Button>
        </CardHeader>
        {loading ? (
          <p className="text-slate-500">Loading forecast…</p>
        ) : chartData.length === 0 ? (
          <p className="text-slate-500">Connect accounts and sync transactions to generate forecasts</p>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <AreaChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="name" stroke="#94a3b8" />
              <YAxis stroke="#94a3b8" />
              <Tooltip />
              <Area type="monotone" dataKey="high" stroke="none" fill="#3B82F620" name="Upper bound" />
              <Area type="monotone" dataKey="balance" stroke="#3B82F6" fill="#3B82F640" name="Projected" />
              <Area type="monotone" dataKey="low" stroke="none" fill="#0f172a" name="Lower bound" />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        {forecasts.map((f) => (
          <Card key={f.horizon_days}>
            <CardHeader>
              <CardTitle className="text-base">{f.horizon_days}-Day Forecast</CardTitle>
            </CardHeader>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-slate-400">Projected balance</dt>
                <dd className="text-white">{formatCurrency(f.projected_balance, currency)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-400">Predicted income</dt>
                <dd className="text-green-400">{formatCurrency(f.predicted_income, currency)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-400">Predicted expenses</dt>
                <dd className="text-red-400">{formatCurrency(f.predicted_expenses, currency)}</dd>
              </div>
              {f.confidence_low != null && f.confidence_high != null && (
                <div className="flex justify-between text-xs text-slate-500">
                  <dt>Range</dt>
                  <dd>
                    {formatCurrency(f.confidence_low, currency)} –{" "}
                    {formatCurrency(f.confidence_high, currency)}
                  </dd>
                </div>
              )}
            </dl>
          </Card>
        ))}
      </div>
    </div>
  );
}
