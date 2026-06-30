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

  const kpis = [
    {
      label: "Total Balance",
      value: balances ? formatCurrency(balances.total_balance, displayCurrency) : "—",
      highlight: true,
    },
    {
      label: "Monthly Income",
      value: metrics ? formatCurrency(metrics.total_income, displayCurrency) : "—",
    },
    {
      label: "Monthly Expenses",
      value: metrics ? formatCurrency(metrics.total_expenses, displayCurrency) : "—",
    },
    {
      label: "Net Cash Flow",
      value: metrics ? formatCurrency(metrics.net_cash_flow, displayCurrency) : "—",
    },
  ];

  return (
    <div className="page-enter min-w-0 space-y-4">
      <div>
        <h1 className="text-xl font-bold text-white md:text-2xl">Dashboard</h1>
        <p className="text-sm text-slate-500">Financial overview</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {kpis.map((kpi) => (
          <Card key={kpi.label}>
            <CardDescription>{kpi.label}</CardDescription>
            {loading ? (
              <Skeleton className="mt-2 h-8 w-28" />
            ) : (
              <p
                className={`mt-2 text-2xl font-bold ${
                  kpi.highlight ? "text-emerald-400" : "text-white"
                }`}
              >
                {kpi.value}
              </p>
            )}
            {kpi.highlight && balances?.as_of && !loading && (
              <p className="mt-1 text-xs text-slate-500">
                Live · {new Date(balances.as_of).toLocaleTimeString()}
              </p>
            )}
          </Card>
        ))}
      </div>

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

      <DashboardCharts transactions={txns} />

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
