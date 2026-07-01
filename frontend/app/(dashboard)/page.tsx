"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatCurrency } from "@/lib/utils";
import { DashboardCharts } from "@/components/dashboard/dashboard-charts";
import { Skeleton, TableRowSkeleton } from "@/components/ui/skeleton";

interface Metrics {
  total_income: number;
  total_expenses: number;
  net_cash_flow: number;
  savings_rate: number | null;
  data_source?: string;
  books_coverage_pct?: number | null;
  books_posted_count?: number | null;
  books_total_count?: number | null;
  cash_in?: number | null;
  cash_out?: number | null;
  qb_unavailable_reason?: string | null;
  period_start?: string;
  period_end?: string;
}

interface Balances {
  total_balance: number;
  primary_currency?: string;
  accounts: Array<{
    institution_name: string;
    name: string;
    mask: string | null;
    current: number;
    currency: string;
  }>;
  as_of: string;
}

interface Transaction {
  id: string;
  transaction_date: string;
  merchant_name: string;
  category: string;
  amount: number;
  transaction_type: string;
  currency?: string;
}

function periodLabel(start?: string, end?: string): string {
  if (!start || !end) return "This month";
  const s = new Date(start);
  const e = new Date(end);
  if (s.getMonth() === e.getMonth() && s.getFullYear() === e.getFullYear()) {
    return s.toLocaleString(undefined, { month: "long", year: "numeric" });
  }
  return `${start} – ${end}`;
}

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [balances, setBalances] = useState<Balances | null>(null);
  const [txns, setTxns] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      apiFetch<Metrics>("/analytics/metrics").catch(() => null),
      apiFetch<Balances>("/analytics/balances").catch(() => null),
      apiFetch<{ items: Transaction[] }>("/transactions?limit=50").catch(() => ({ items: [] })),
    ]).then(([m, b, t]) => {
      setMetrics(m);
      setBalances(b);
      setTxns(t?.items ?? []);
      setLoading(false);
    });
  }, []);

  const displayCurrency =
    balances?.primary_currency || balances?.accounts[0]?.currency || "NGN";

  const fromQb = metrics?.data_source === "quickbooks";
  const period = periodLabel(metrics?.period_start, metrics?.period_end);

  const kpis = [
    {
      label: "Total Balance",
      sub: "Live bank balance",
      value: balances ? formatCurrency(balances.total_balance, displayCurrency) : "—",
      highlight: true,
    },
    {
      label: fromQb ? "Revenue (QuickBooks)" : "Cash in (bank)",
      sub: period,
      value: metrics ? formatCurrency(metrics.total_income, displayCurrency) : "—",
    },
    {
      label: fromQb ? "Expenses (QuickBooks)" : "Cash out (bank)",
      sub: period,
      value: metrics ? formatCurrency(metrics.total_expenses, displayCurrency) : "—",
    },
    {
      label: fromQb ? "Net profit (QuickBooks)" : "Net cash flow (bank)",
      sub: period,
      value: metrics ? formatCurrency(metrics.net_cash_flow, displayCurrency) : "—",
    },
  ];

  return (
    <div className="page-enter min-w-0 space-y-4">
      <div>
        <h1 className="text-xl font-bold text-white md:text-2xl">Dashboard</h1>
        <p className="text-sm text-slate-500">Financial overview</p>
      </div>

      {!loading && metrics && (
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={fromQb ? "success" : "secondary"}>
            {fromQb ? "P&L from QuickBooks" : "Bank cash view"}
          </Badge>
          {metrics.books_total_count != null && metrics.books_total_count > 0 && (
            <Badge variant="secondary" className="text-xs">
              Books posted {metrics.books_posted_count ?? 0}/{metrics.books_total_count}
              {metrics.books_coverage_pct != null ? ` (${metrics.books_coverage_pct}%)` : ""}
            </Badge>
          )}
          {metrics.qb_unavailable_reason && (
            <span className="text-xs text-amber-400">{metrics.qb_unavailable_reason}</span>
          )}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {kpis.map((kpi) => (
          <Card key={kpi.label}>
            <CardDescription>{kpi.label}</CardDescription>
            {loading ? (
              <Skeleton className="mt-2 h-8 w-28" />
            ) : (
              <>
                <p
                  className={`mt-2 text-2xl font-bold ${
                    kpi.highlight ? "text-emerald-400" : "text-white"
                  }`}
                >
                  {kpi.value}
                </p>
                {kpi.sub && (
                  <p className="mt-1 text-xs text-slate-500">{kpi.sub}</p>
                )}
              </>
            )}
            {kpi.highlight && balances?.as_of && !loading && (
              <p className="mt-1 text-xs text-slate-500">
                Live · {new Date(balances.as_of).toLocaleTimeString()}
              </p>
            )}
          </Card>
        ))}
      </div>

      {!loading && fromQb && metrics?.cash_in != null && metrics?.cash_out != null && (
        <p className="text-xs text-slate-500">
          Bank cash movement this month (reference): in {formatCurrency(metrics.cash_in, displayCurrency)} · out{" "}
          {formatCurrency(metrics.cash_out, displayCurrency)}
        </p>
      )}

      {balances && balances.accounts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Balances by account</CardTitle>
          </CardHeader>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {balances.accounts.map((acct, i) => (
              <div
                key={i}
                className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3"
              >
                <p className="text-sm text-slate-400">{acct.institution_name}</p>
                <p className="font-medium text-white">
                  {acct.name}
                  {acct.mask && <span className="text-slate-500"> ···{acct.mask}</span>}
                </p>
                <p className="mt-1 text-lg font-bold text-emerald-400">
                  {formatCurrency(acct.current, acct.currency)}
                </p>
              </div>
            ))}
          </div>
        </Card>
      )}

      <DashboardCharts transactions={txns} currency={displayCurrency} />

      <Card>
        <CardHeader>
          <CardTitle>Recent Transactions</CardTitle>
        </CardHeader>
        <div className="overflow-hidden">
          <table className="table-fit text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-slate-400">
                <th className="pb-2">Date</th>
                <th className="pb-2">Merchant</th>
                <th className="pb-2">Category</th>
                <th className="pb-2 text-right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => <TableRowSkeleton key={i} cols={4} />)
              ) : txns.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-8 text-center text-slate-500">
                    Connect a bank account to see transactions
                  </td>
                </tr>
              ) : (
                txns.slice(0, 10).map((txn) => (
                  <tr key={txn.id} className="border-b border-slate-800/50">
                    <td className="py-3 text-slate-400">{txn.transaction_date}</td>
                    <td className="max-w-0 py-3">
                      <span className="cell-truncate block text-white">{txn.merchant_name}</span>
                    </td>
                    <td className="max-w-0 py-3">
                      <Badge className="max-w-full truncate">{txn.category || "Uncategorized"}</Badge>
                    </td>
                    <td
                      className={`py-3 text-right ${txn.transaction_type === "credit" ? "text-green-400" : "text-white"}`}
                    >
                      {txn.transaction_type === "credit" ? "+" : "-"}
                      {formatCurrency(txn.amount, txn.currency || displayCurrency)}
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
