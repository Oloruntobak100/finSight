"use client";

import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { FileText, RefreshCw, Sparkles, BookOpen } from "lucide-react";
import { apiFetch, normalizeApiBase } from "@/lib/api";
import { fetchQbPnl } from "@/lib/books";
import {
  buildAnalysisQueryString,
  filterSummaryChips,
  getDefaultAnalysisFilters,
  loadAnalysisFilters,
  saveAnalysisFilters,
  type AnalysisFilterState,
  type AnalyticsMetaAccount,
} from "@/lib/analysis-filters";
import { AnalysisFiltersBar } from "@/components/analysis/analysis-filters";
import { AnalyticsSection, KpiCard } from "@/components/analysis/analytics-primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable as InteractiveDataTable } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { formatCategory, formatCurrency } from "@/lib/utils";

interface ReportData {
  generated_at: string;
  primary_currency?: string;
  period: { start: string; end: string; label: string };
  executive_summary: {
    bullets: string[];
    total_balance: number;
    monthly_income: number;
    monthly_expenses: number;
    net_cash_flow: number;
    savings_rate: number | null;
    transaction_count: number;
  };
  monthly_trend: Array<{ month: string; income: number; expenses: number; net: number }>;
  yearly_trend?: Array<{ year: string; income: number; expenses: number; net: number }>;
  category_spending: Array<{ category: string; amount: number; pct: number }>;
  bank_summary: Array<{
    bank: string;
    provider?: string;
    currency?: string;
    income: number;
    expenses: number;
    net: number;
    transaction_count: number;
  }>;
  top_merchants: Array<{ merchant: string; amount: number; count: number }>;
  month_transactions: Array<{
    id: string;
    date: string;
    bank: string;
    merchant: string;
    category: string;
    type: string;
    amount: number;
    currency: string;
    is_recurring: boolean;
  }>;
  largest_expenses: Array<{ merchant: string; amount: number; date: string; bank: string; category: string }>;
  income_transactions: Array<{ merchant: string; amount: number; date: string; bank: string }>;
  weekly_breakdown: Array<{ week: string; income: number; expenses: number; net: number; transaction_count: number }>;
  subscriptions: { items: Array<{ merchant_name: string; amount: number; annual_cost: number }>; total_monthly: number };
  period_comparison: {
    label?: string;
    income_change_pct: number | null;
    expense_change_pct: number | null;
    net_change_pct: number | null;
    transfer_volume_change_pct?: number | null;
  };
  transfer_activity?: {
    transfer_in: number;
    transfer_out: number;
    count: number;
    top_counterparties?: Array<{ counterparty: string; volume: number; count: number }>;
  };
  counterparty_flows?: Array<{ counterparty: string; sent: number; received: number; net: number; count: number }>;
  anomalies?: Array<{ date: string; counterparty: string; amount: number; currency: string; reason: string }>;
  insights?: Array<{ title: string; body: string; type: string }>;
  spending_habits?: {
    weekday_spend?: number;
    weekend_spend?: number;
    channel_mix?: Array<{ channel: string; amount: number; pct: number }>;
  };
}

interface QbPnlSection {
  section: string;
  label: string;
  amount: number;
}

interface QbPnlData {
  report_name?: string;
  start_date?: string;
  end_date?: string;
  sections: QbPnlSection[];
  cached?: boolean;
  fetched_at?: string;
}

type Tab = "overview" | "monthly" | "spending" | "transfers" | "transactions" | "insights" | "ai";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "monthly", label: "Monthly" },
  { id: "spending", label: "Spending" },
  { id: "transfers", label: "Transfers" },
  { id: "transactions", label: "Transactions" },
  { id: "insights", label: "Insights" },
  { id: "ai", label: "AI CFO" },
];

function DataTable({
  headers,
  rows,
  empty = "No data",
}: {
  headers: string[];
  rows: React.ReactNode[][];
  empty?: string;
}) {
  if (rows.length === 0) {
    return <p className="py-6 text-center text-sm text-slate-500">{empty}</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-800 text-left text-slate-400">
            {headers.map((h) => (
              <th key={h} className="pb-2 pr-4 last:pr-0">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-slate-800/50">
              {row.map((cell, j) => (
                <td key={j} className="py-3 pr-4 text-slate-200 last:pr-0">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ReportsPage() {
  const [filters, setFilters] = useState(getDefaultAnalysisFilters);
  const [accounts, setAccounts] = useState<AnalyticsMetaAccount[]>([]);
  const [report, setReport] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<Tab>("overview");
  const [aiText, setAiText] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [qbPnl, setQbPnl] = useState<QbPnlData | null>(null);
  const [qbPnlLoading, setQbPnlLoading] = useState(false);
  const [qbPnlError, setQbPnlError] = useState<string | null>(null);

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

  const load = useCallback(async (f: AnalysisFilterState, quiet = false) => {
    if (!quiet) setLoading(true);
    else setRefreshing(true);
    try {
      const qs = buildAnalysisQueryString(f);
      const data = await apiFetch<ReportData>(`/reports/comprehensive?${qs}`);
      setReport(data);
    } catch {
      setReport(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load(filters);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function applyFilters() {
    saveAnalysisFilters(filters);
    load(filters);
    loadQbPnl(filters, false);
  }

  const loadQbPnl = useCallback(async (f: AnalysisFilterState, refresh = false) => {
    setQbPnlLoading(true);
    setQbPnlError(null);
    try {
      const data = (await fetchQbPnl(f.dateFrom, f.dateTo, refresh)) as QbPnlData;
      setQbPnl(data);
    } catch (err) {
      setQbPnl(null);
      setQbPnlError(err instanceof Error ? err.message : "QuickBooks P&L unavailable");
    } finally {
      setQbPnlLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === "overview") {
      loadQbPnl(filters, false);
    }
  }, [tab, filters.dateFrom, filters.dateTo, loadQbPnl]);

  async function generateAiInsights() {
    setAiLoading(true);
    setAiError(null);
    setAiText("");
    try {
      const { createClient } = await import("@/lib/supabase/client");
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) throw new Error("Not authenticated");

      const streamRes = await fetch(
        `${normalizeApiBase(process.env.NEXT_PUBLIC_FASTAPI_URL)}/reports/ai-insights`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${session.access_token}` },
        }
      );
      if (!streamRes.ok) {
        const err = await streamRes.json().catch(() => ({ detail: "Failed" }));
        throw new Error(err.detail || "AI insights failed");
      }
      const reader = streamRes.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) throw new Error("No stream");
      let text = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        text += decoder.decode(value);
        setAiText(text);
      }
    } catch (err) {
      setAiError(err instanceof Error ? err.message : "Could not generate insights");
    } finally {
      setAiLoading(false);
    }
  }

  if (loading && !report) {
    return (
      <div className="page-enter space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-12 w-full max-w-xl" />
        <Skeleton className="h-96 rounded-xl" />
      </div>
    );
  }

  if (!report) {
    return (
      <div className="page-enter space-y-4">
        <h1 className="text-2xl font-bold text-white">Reports</h1>
        <p className="text-red-300">Could not load report data.</p>
        <Button onClick={() => load(filters)}>Retry</Button>
      </div>
    );
  }

  const { executive_summary, period } = report;
  const currency = report.primary_currency || "USD";
  const fmt = (n: number, c?: string) => formatCurrency(n, c || currency);
  const chips = filterSummaryChips(filters, accounts);

  return (
    <div className="page-enter space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
            <FileText className="h-6 w-6 text-blue-400" />
            Reports
          </h1>
          <p className="text-slate-400">
            {period.label} · Generated {new Date(report.generated_at).toLocaleDateString()}
          </p>
        </div>
        <Button variant="outline" loading={refreshing} loadingLabel="Refreshing…" onClick={() => load(filters, true)}>
          <RefreshCw className="h-4 w-4" />
          Refresh report
        </Button>
      </div>

      <AnalysisFiltersBar
        filters={filters}
        accounts={accounts}
        onChange={setFilters}
        onApply={applyFilters}
        loading={refreshing}
      />

      <div className="flex flex-wrap gap-2">
        {chips.map((chip) => (
          <Badge key={chip} variant="secondary" className="text-xs">
            {chip}
          </Badge>
        ))}
      </div>

      <div className="flex gap-1 overflow-x-auto rounded-lg border border-slate-800/60 bg-slate-950/40 p-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`shrink-0 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              tab === t.id ? "bg-blue-600 text-white shadow-sm" : "text-slate-400 hover:bg-slate-800/80 hover:text-white"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <KpiCard label="Total balance" value={fmt(executive_summary.total_balance)} accent="positive" />
            <KpiCard label="Period income" value={fmt(executive_summary.monthly_income)} />
            <KpiCard label="Period expenses" value={fmt(executive_summary.monthly_expenses)} />
            <KpiCard
              label="Net cash flow"
              value={fmt(executive_summary.net_cash_flow)}
              accent={executive_summary.net_cash_flow >= 0 ? "positive" : "negative"}
            />
          </div>

          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div>
                <CardTitle className="flex items-center gap-2 text-base">
                  <BookOpen className="h-4 w-4 text-emerald-400" />
                  QuickBooks Profit &amp; Loss
                </CardTitle>
                <CardDescription>
                  {qbPnl?.start_date && qbPnl?.end_date
                    ? `${qbPnl.start_date} → ${qbPnl.end_date}`
                    : `${filters.dateFrom} → ${filters.dateTo}`}
                  {qbPnl?.cached ? " · cached" : qbPnl?.fetched_at ? " · live" : ""}
                </CardDescription>
              </div>
              <Button
                variant="outline"
                size="sm"
                loading={qbPnlLoading}
                loadingLabel="Loading…"
                onClick={() => loadQbPnl(filters, true)}
              >
                <RefreshCw className="h-4 w-4" />
                Refresh P&amp;L
              </Button>
            </CardHeader>
            {qbPnlLoading && !qbPnl && (
              <div className="flex items-center gap-2 px-6 pb-6 text-sm text-slate-400">
                <Spinner size="sm" />
                Loading QuickBooks report…
              </div>
            )}
            {qbPnlError && (
              <p className="px-6 pb-6 text-sm text-slate-500">
                {qbPnlError}. Connect QuickBooks in Settings to see books P&amp;L here.
              </p>
            )}
            {qbPnl && qbPnl.sections.length > 0 && (
              <DataTable
                headers={["Section", "Line item", "Amount"]}
                rows={qbPnl.sections.slice(0, 40).map((row) => [
                  row.section,
                  row.label,
                  fmt(row.amount),
                ])}
                empty="No P&L lines for this period"
              />
            )}
            {qbPnl && qbPnl.sections.length === 0 && !qbPnlLoading && (
              <p className="px-6 pb-6 text-sm text-slate-500">No P&amp;L data for this period.</p>
            )}
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Executive summary</CardTitle>
              <CardDescription>Key findings for {period.label}</CardDescription>
            </CardHeader>
            <ul className="list-inside list-disc space-y-2 text-sm text-slate-300">
              {executive_summary.bullets.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Period comparison{report.period_comparison.label ? ` — ${report.period_comparison.label}` : ""}
              </CardTitle>
            </CardHeader>
            <DataTable
              headers={["Metric", "Change"]}
              rows={[
                ["Income", pct(report.period_comparison.income_change_pct)],
                ["Expenses", pct(report.period_comparison.expense_change_pct)],
                ["Net cash flow", pct(report.period_comparison.net_change_pct)],
                ...(report.period_comparison.transfer_volume_change_pct != null
                  ? [["Transfer volume", pct(report.period_comparison.transfer_volume_change_pct)]]
                  : []),
              ]}
            />
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Weekly breakdown (this month)</CardTitle>
            </CardHeader>
            <DataTable
              headers={["Week", "Income", "Expenses", "Net", "Txns"]}
              rows={report.weekly_breakdown.map((w) => [
                w.week,
                <span key={`${w.week}-in`} className="text-emerald-400">+{fmt(w.income)}</span>,
                <span key={`${w.week}-ex`} className="text-slate-300">-{fmt(w.expenses)}</span>,
                <span key={`${w.week}-net`} className={w.net >= 0 ? "text-emerald-400" : "text-red-400"}>{fmt(w.net)}</span>,
                String(w.transaction_count),
              ])}
              empty="No transactions this month"
            />
          </Card>
        </div>
      )}

      {tab === "monthly" && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Monthly trend</CardTitle>
              <CardDescription>Income, expenses, and net</CardDescription>
            </CardHeader>
            <DataTable
              headers={["Month", "Income", "Expenses", "Net"]}
              rows={report.monthly_trend.map((m) => [
                m.month,
                <span key={`${m.month}-in`} className="text-emerald-400">+{fmt(m.income)}</span>,
                <span key={`${m.month}-ex`} className="text-slate-300">-{fmt(m.expenses)}</span>,
                <span key={`${m.month}-net`} className={m.net >= 0 ? "text-emerald-400 font-medium" : "text-red-400 font-medium"}>
                  {fmt(m.net)}
                </span>,
              ])}
            />
          </Card>
          {(report.yearly_trend?.length ?? 0) > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Yearly trend</CardTitle>
              </CardHeader>
              <DataTable
                headers={["Year", "Income", "Expenses", "Net"]}
                rows={(report.yearly_trend ?? []).map((y) => [
                  y.year,
                  <span key={`${y.year}-in`} className="text-emerald-400">+{fmt(y.income)}</span>,
                  <span key={`${y.year}-ex`} className="text-slate-300">-{fmt(y.expenses)}</span>,
                  <span key={`${y.year}-net`} className={y.net >= 0 ? "text-emerald-400 font-medium" : "text-red-400 font-medium"}>
                    {fmt(y.net)}
                  </span>,
                ])}
              />
            </Card>
          )}
        </div>
      )}

      {tab === "spending" && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Spending by category</CardTitle>
            </CardHeader>
            <DataTable
              headers={["Category", "Amount", "Share"]}
              rows={report.category_spending.map((c) => [
                <Badge key={c.category}>{formatCategory(c.category)}</Badge>,
                fmt(c.amount),
                `${c.pct}%`,
              ])}
            />
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">By bank</CardTitle>
            </CardHeader>
            <DataTable
              headers={["Bank", "Income", "Expenses", "Net", "Transactions"]}
              rows={report.bank_summary.map((b) => [
                <span key={`${b.bank}-label`}>
                  {b.bank}
                  {b.provider && (
                    <span className="ml-2 text-xs text-slate-500">({b.provider})</span>
                  )}
                </span>,
                <span key={`${b.bank}-in`} className="text-emerald-400">+{fmt(b.income, b.currency)}</span>,
                <span key={`${b.bank}-ex`} className="text-slate-300">-{fmt(b.expenses, b.currency)}</span>,
                <span key={`${b.bank}-net`} className={b.net >= 0 ? "text-emerald-400" : "text-red-400"}>{fmt(b.net, b.currency)}</span>,
                String(b.transaction_count),
              ])}
            />
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Top merchants</CardTitle>
            </CardHeader>
            <DataTable
              headers={["Merchant", "Total spent", "Transactions"]}
              rows={report.top_merchants.map((m) => [
                m.merchant,
                fmt(m.amount),
                String(m.count),
              ])}
            />
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Recurring subscriptions</CardTitle>
              <CardDescription>
                {fmt(report.subscriptions.total_monthly)}/month detected
              </CardDescription>
            </CardHeader>
            <DataTable
              headers={["Merchant", "Monthly", "Annual"]}
              rows={report.subscriptions.items.map((s) => [
                s.merchant_name,
                fmt(s.amount),
                fmt(s.annual_cost),
              ])}
              empty="No recurring charges detected"
            />
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Largest expenses (this month)</CardTitle>
            </CardHeader>
            <DataTable
              headers={["Date", "Bank", "Merchant", "Category", "Amount"]}
              rows={report.largest_expenses.map((t) => [
                t.date,
                t.bank,
                t.merchant,
                <Badge key={`${t.merchant}-cat`}>{formatCategory(t.category)}</Badge>,
                <span key={`${t.merchant}-amt`} className="font-medium text-white">-{fmt(t.amount)}</span>,
              ])}
            />
          </Card>
        </div>
      )}

      {tab === "transfers" && (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <Card>
              <CardDescription>Transfer in</CardDescription>
              <p className="mt-2 text-2xl font-bold text-emerald-400">
                {fmt(report.transfer_activity?.transfer_in ?? 0)}
              </p>
            </Card>
            <Card>
              <CardDescription>Transfer out</CardDescription>
              <p className="mt-2 text-2xl font-bold text-red-400">
                {fmt(report.transfer_activity?.transfer_out ?? 0)}
              </p>
            </Card>
            <Card>
              <CardDescription>Transfer count</CardDescription>
              <p className="mt-2 text-2xl font-bold text-white">{report.transfer_activity?.count ?? 0}</p>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Top transfer counterparties</CardTitle>
            </CardHeader>
            <DataTable
              headers={["Counterparty", "Volume", "Count"]}
              rows={(report.transfer_activity?.top_counterparties ?? []).map((c) => [
                c.counterparty,
                fmt(c.volume),
                String(c.count),
              ])}
              empty="No transfer activity in this period"
            />
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Counterparty flows</CardTitle>
              <CardDescription>Sent vs received (net position)</CardDescription>
            </CardHeader>
            <DataTable
              headers={["Counterparty", "Sent", "Received", "Net", "Txns"]}
              rows={(report.counterparty_flows ?? []).map((c) => [
                c.counterparty,
                fmt(c.sent),
                fmt(c.received),
                <span key={`${c.counterparty}-net`} className={c.net >= 0 ? "text-emerald-400" : "text-red-400"}>{fmt(c.net)}</span>,
                String(c.count),
              ])}
              empty="No counterparty data"
            />
          </Card>

          {(report.anomalies?.length ?? 0) > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Anomalies</CardTitle>
                <CardDescription>Unusual transactions flagged by amount or first-time payee</CardDescription>
              </CardHeader>
              <DataTable
                headers={["Date", "Counterparty", "Amount", "Reason"]}
                rows={(report.anomalies ?? []).map((a) => [
                  a.date,
                  a.counterparty,
                  fmt(a.amount, a.currency),
                  a.reason,
                ])}
              />
            </Card>
          )}
        </div>
      )}

      {tab === "insights" && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Auto-generated insights</CardTitle>
              <CardDescription>Plain-English takeaways from your filtered data</CardDescription>
            </CardHeader>
            {(report.insights?.length ?? 0) === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">No insights for this filter set</p>
            ) : (
              <ul className="space-y-4">
                {(report.insights ?? []).map((insight, i) => (
                  <li key={i} className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                    <p className="font-medium text-white">{insight.title}</p>
                    <p className="mt-1 text-sm text-slate-400">{insight.body}</p>
                    <Badge variant="secondary" className="mt-2 text-xs capitalize">
                      {insight.type}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {report.spending_habits && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Spending habits</CardTitle>
              </CardHeader>
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <p className="text-sm text-slate-400">Weekday spend</p>
                  <p className="text-lg font-semibold text-white">{fmt(report.spending_habits.weekday_spend ?? 0)}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-400">Weekend spend</p>
                  <p className="text-lg font-semibold text-white">{fmt(report.spending_habits.weekend_spend ?? 0)}</p>
                </div>
              </div>
              {(report.spending_habits.channel_mix?.length ?? 0) > 0 && (
                <DataTable
                  headers={["Channel", "Amount", "Share"]}
                  rows={(report.spending_habits.channel_mix ?? []).map((ch) => [
                    ch.channel,
                    fmt(ch.amount),
                    `${ch.pct}%`,
                  ])}
                />
              )}
            </Card>
          )}
        </div>
      )}

      {tab === "transactions" && (
        <AnalyticsSection
          title={`All transactions — ${period.label}`}
          description={`${report.month_transactions.length} records · sortable & searchable`}
        >
          <InteractiveDataTable
            pageSize={15}
            searchKeys={["merchant", "bank", "category"]}
            data={report.month_transactions}
            columns={[
              { key: "date", header: "Date", sortable: true, render: (t) => t.date, sortValue: (t) => t.date },
              { key: "bank", header: "Bank", sortable: true, render: (t) => t.bank, sortValue: (t) => t.bank },
              {
                key: "merchant",
                header: "Merchant",
                sortable: true,
                render: (t) => (
                  <>
                    {t.merchant}
                    {t.is_recurring && (
                      <Badge variant="warning" className="ml-2 text-xs">
                        Recurring
                      </Badge>
                    )}
                  </>
                ),
                sortValue: (t) => t.merchant,
              },
              { key: "category", header: "Category", render: (t) => <Badge>{formatCategory(t.category)}</Badge> },
              { key: "type", header: "Type", render: (t) => <span className="capitalize">{t.type}</span> },
              {
                key: "amount",
                header: "Amount",
                align: "right",
                sortable: true,
                sortValue: (t) => t.amount,
                render: (t) => (
                  <span className={t.type === "credit" ? "text-emerald-400 font-medium" : "text-white font-medium"}>
                    {t.type === "credit" ? "+" : "−"}
                    {formatCurrency(t.amount, t.currency)}
                  </span>
                ),
              },
            ]}
          />
        </AnalyticsSection>
      )}

      {tab === "ai" && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Sparkles className="h-4 w-4 text-amber-400" />
              AI CFO Report
            </CardTitle>
            <CardDescription>
              Executive narrative written from your live financial data
            </CardDescription>
          </CardHeader>
          {!aiText && !aiLoading && (
            <Button onClick={generateAiInsights} className="mb-4">
              Generate AI insights
            </Button>
          )}
          {aiLoading && (
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <Spinner size="sm" className="text-blue-400" />
              Analyzing your finances…
            </div>
          )}
          {aiError && <p className="text-sm text-red-300">{aiError}</p>}
          {aiText && (
            <div className="prose prose-invert max-w-none text-sm text-slate-300">
              <ReactMarkdown>{aiText}</ReactMarkdown>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

function pct(value: number | null) {
  if (value == null) return "—";
  const color = value >= 0 ? "text-emerald-400" : "text-red-400";
  return (
    <span className={color}>
      {value >= 0 ? "+" : ""}
      {value.toFixed(1)}%
    </span>
  );
}
