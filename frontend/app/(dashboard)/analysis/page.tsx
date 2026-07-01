"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { RefreshCw, TrendingDown, TrendingUp } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { AnalyticsSection, KpiCard } from "@/components/analysis/analytics-primitives";
import type { AnalyticsView } from "@/components/analysis/analytics-view-nav";
import { AnalysisFiltersBar } from "@/components/analysis/analysis-filters";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { PageLoader } from "@/components/ui/page-loader";
import {
  buildAnalysisQueryString,
  filterSummaryChips,
  getDefaultAnalysisFilters,
  loadAnalysisFilters,
  saveAnalysisFilters,
  type AnalyticsMetaAccount,
} from "@/lib/analysis-filters";
import { formatCategory, formatCurrency } from "@/lib/utils";
import { providerDisplayName } from "@/lib/provider-labels";

const EMPTY_PERIOD = {
  label: "No comparison",
  current: { income: 0, expenses: 0, net: 0, transfer_volume: 0 },
  previous: { income: 0, expenses: 0, net: 0, transfer_volume: 0 },
  income_change_pct: null as number | null,
  expense_change_pct: null as number | null,
  net_change_pct: null as number | null,
  transfer_volume_change_pct: null as number | null,
};

interface AnalysisData {
  primary_currency: string;
  currencies: string[];
  balances: {
    total_balance: number;
    accounts: Array<{ name: string; current: number; currency: string; provider?: string }>;
  };
  metrics: { total_income: number; total_expenses: number; net_cash_flow: number; savings_rate: number | null };
  monthly_trend: Array<{ month: string; income: number; expenses: number; net: number }>;
  yearly_trend: Array<{ year: string; income: number; expenses: number; net: number }>;
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
  daily_cashflow: Array<{ date: string; net: number }>;
  period_comparison: typeof EMPTY_PERIOD;
  spending_habits: {
    weekday_vs_weekend?: { weekday: number; weekend: number; weekend_pct: number };
    channel_mix?: Array<{ channel: string; amount: number; pct: number }>;
    category_drift?: Array<{ category: string; current: number; previous: number; change_pct: number | null }>;
  };
  income_insights: {
    stability_score?: number | null;
    salary_candidates?: Array<{ counterparty: string; avg_amount: number; count: number }>;
    next_payday_estimate?: string | null;
    monthly_income_avg?: number;
  };
  cash_runway: Array<{
    account_name: string;
    currency: string;
    balance: number;
    avg_daily_net_burn: number;
    days_of_runway: number | null;
  }>;
  counterparty_flows: Array<{ counterparty: string; sent: number; received: number; net: number; count: number }>;
  transfer_activity: {
    transfer_in: number;
    transfer_out: number;
    count: number;
    top_counterparties: Array<{ counterparty: string; volume: number; count: number }>;
  };
  anomalies: Array<{ date: string; counterparty: string; amount: number; currency: string; reason: string }>;
  recurring_detected: Array<{ name: string; amount: number; currency: string; source: string; count?: number }>;
  account_comparison: {
    account_a: Record<string, unknown>;
    account_b: Record<string, unknown>;
    deltas: Record<string, number | null>;
    category_diff: Array<{ category: string; amount_a: number; amount_b: number; delta_pct: number | null }>;
  } | null;
  insights: Array<{ title: string; body: string; type: string }>;
  transaction_count: number;
  data_source?: string;
  qb_unavailable_reason?: string | null;
  books_coverage?: {
    posted_count?: number;
    total_count?: number;
    coverage_pct?: number | null;
  };
  bank_activity?: {
    metrics?: { total_income: number; total_expenses: number; net_cash_flow: number };
    top_merchants?: Array<{ merchant: string; amount: number; count: number }>;
    bank_summary?: AnalysisData["bank_summary"];
    transfer_activity?: AnalysisData["transfer_activity"];
    counterparty_flows?: AnalysisData["counterparty_flows"];
    anomalies?: AnalysisData["anomalies"];
    recurring_detected?: AnalysisData["recurring_detected"];
    transaction_count?: number;
  };
}

function normalizeAnalysisData(raw: Partial<AnalysisData> & { primary_currency?: string }): AnalysisData {
  const primary = raw.primary_currency || "USD";
  const pc = raw.period_comparison;
  return {
    primary_currency: primary,
    currencies: raw.currencies?.length ? raw.currencies : [primary],
    balances: raw.balances ?? { total_balance: 0, accounts: [] },
    metrics: raw.metrics ?? { total_income: 0, total_expenses: 0, net_cash_flow: 0, savings_rate: null },
    monthly_trend: raw.monthly_trend ?? [],
    yearly_trend: raw.yearly_trend ?? [],
    category_spending: raw.category_spending ?? [],
    bank_summary: raw.bank_summary ?? [],
    top_merchants: raw.top_merchants ?? [],
    daily_cashflow: raw.daily_cashflow ?? [],
    period_comparison: {
      ...EMPTY_PERIOD,
      ...pc,
      current: { ...EMPTY_PERIOD.current, ...pc?.current },
      previous: { ...EMPTY_PERIOD.previous, ...pc?.previous },
    },
    spending_habits: raw.spending_habits ?? {},
    income_insights: raw.income_insights ?? {},
    cash_runway: raw.cash_runway ?? [],
    counterparty_flows: raw.counterparty_flows ?? [],
    transfer_activity: raw.transfer_activity ?? {
      transfer_in: 0,
      transfer_out: 0,
      count: 0,
      top_counterparties: [],
    },
    anomalies: raw.anomalies ?? [],
    recurring_detected: raw.recurring_detected ?? [],
    account_comparison: raw.account_comparison ?? null,
    insights: raw.insights ?? [],
    transaction_count: raw.transaction_count ?? 0,
    data_source: raw.data_source,
    qb_unavailable_reason: raw.qb_unavailable_reason,
    books_coverage: raw.books_coverage,
    bank_activity: raw.bank_activity,
  };
}

function TrendBadge({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-slate-500">—</span>;
  const up = value >= 0;
  return (
    <span className={`inline-flex items-center gap-0.5 ${up ? "text-emerald-400" : "text-red-400"}`}>
      {up ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
      {up ? "+" : ""}
      {value.toFixed(1)}%
    </span>
  );
}

export default function AnalysisPage() {
  const searchParams = useSearchParams();
  const view = (searchParams.get("view") as AnalyticsView) || "overview";

  const [filters, setFilters] = useState(getDefaultAnalysisFilters);
  const [accounts, setAccounts] = useState<AnalyticsMetaAccount[]>([]);
  const [data, setData] = useState<AnalysisData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

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

  const load = useCallback(async (quiet = false, f = filters) => {
    if (!quiet) setLoading(true);
    else setRefreshing(true);
    try {
      const qs = buildAnalysisQueryString(f);
      const result = await apiFetch<AnalysisData>(`/analytics/analysis?${qs}`);
      setData(normalizeAnalysisData(result));
    } catch {
      setData(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [filters]);

  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const currency = data?.primary_currency || "USD";
  const fmt = (n: number, cur = currency) => formatCurrency(n, cur);
  const pc = data?.period_comparison ?? EMPTY_PERIOD;
  const fromQb = data?.data_source === "quickbooks";
  const bankAct = data?.bank_activity;

  const bankRows = useMemo(
    () =>
      (data?.bank_summary ?? []).map((r, i) => ({
        id: `bank-${i}`,
        bank: r.bank,
        provider: providerDisplayName(r.provider),
        income: r.income,
        expenses: r.expenses,
        net: r.net,
        currency: r.currency || currency,
        transaction_count: r.transaction_count,
      })),
    [data?.bank_summary, currency]
  );

  if (loading && !data) {
    return <PageLoader message="Loading analysis…" />;
  }

  return (
    <div className="page-enter space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Analysis</h1>
          <p className="mt-1 text-sm text-slate-500">
            {fromQb ? "QuickBooks P&L" : "Bank cash view"} · {data?.transaction_count ?? 0} bank transactions
          </p>
        </div>
        <Button variant="outline" size="sm" loading={refreshing} onClick={() => load(true)}>
          <RefreshCw className="h-4 w-4" />
          Refresh
        </Button>
      </div>

      <AnalysisFiltersBar
        filters={filters}
        accounts={accounts}
        onChange={setFilters}
        onApply={() => {
          saveAnalysisFilters(filters);
          load(false, filters);
        }}
        loading={refreshing}
      />

      {data && (
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={fromQb ? "success" : "secondary"}>
            {fromQb ? "Accounting data from QuickBooks" : "Bank cash movement (QuickBooks unavailable)"}
          </Badge>
          {data.books_coverage?.total_count != null && data.books_coverage.total_count > 0 && (
            <Badge variant="secondary" className="text-xs font-normal">
              Books posted {data.books_coverage.posted_count ?? 0}/{data.books_coverage.total_count}
              {data.books_coverage.coverage_pct != null ? ` (${data.books_coverage.coverage_pct}%)` : ""}
            </Badge>
          )}
          {data.qb_unavailable_reason && (
            <span className="text-xs text-amber-400">{data.qb_unavailable_reason}</span>
          )}
          {filterSummaryChips(filters, accounts).map((chip) => (
            <Badge key={chip} variant="secondary" className="text-xs font-normal">
              {chip}
            </Badge>
          ))}
        </div>
      )}

      {!data ? (
        <p className="text-red-300">Could not load analysis. Check the backend is running.</p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <KpiCard
              label={`Balance (${currency})`}
              value={fmt(data.balances.total_balance)}
              accent="positive"
            />
            <KpiCard
              label={fromQb ? "Revenue (QuickBooks)" : "Cash in (bank)"}
              value={fmt(data.metrics.total_income)}
              trend={
                <>
                  vs prior <TrendBadge value={pc.income_change_pct} />
                </>
              }
            />
            <KpiCard
              label={fromQb ? "Expenses (QuickBooks)" : "Cash out (bank)"}
              value={fmt(data.metrics.total_expenses)}
              trend={
                <>
                  vs prior <TrendBadge value={pc.expense_change_pct} />
                </>
              }
            />
            <KpiCard
              label={fromQb ? "Net profit (QuickBooks)" : "Net cash flow (bank)"}
              value={fmt(data.metrics.net_cash_flow)}
              accent={data.metrics.net_cash_flow >= 0 ? "positive" : "negative"}
              sub={<span>{pc.label}</span>}
            />
          </div>

          {fromQb && bankAct?.metrics && (
            <p className="text-xs text-slate-500">
              Bank reference for same filters: in {fmt(bankAct.metrics.total_income)} · out{" "}
              {fmt(bankAct.metrics.total_expenses)} · net {fmt(bankAct.metrics.net_cash_flow)}
            </p>
          )}

          {view === "overview" && <OverviewView data={data} fmt={fmt} bankRows={bankRows} fromQb={fromQb} />}
          {view === "spending" && <SpendingView data={data} fmt={fmt} fromQb={fromQb} />}
          {view === "income" && <IncomeView data={data} fmt={fmt} fromQb={fromQb} />}
          {view === "bank" && <BankActivityView data={data} fmt={fmt} />}
          {view === "transfers" && <TransfersView data={data} fmt={fmt} />}
          {view === "compare" && <CompareView data={data} fmt={fmt} pc={pc} fromQb={fromQb} />}
          {view === "insights" && <InsightsView data={data} fmt={fmt} />}
        </>
      )}
    </div>
  );
}

type Fmt = (n: number, cur?: string) => string;

function OverviewView({
  data,
  fmt,
  bankRows,
  fromQb,
}: {
  data: AnalysisData;
  fmt: Fmt;
  bankRows: Array<{
    id: string;
    bank: string;
    provider: string;
    income: number;
    expenses: number;
    net: number;
    currency: string;
    transaction_count: number;
  }>;
  fromQb: boolean;
}) {
  const bankCols: DataTableColumn<(typeof bankRows)[0]>[] = [
    { key: "bank", header: "Account", sortable: true, render: (r) => r.bank, sortValue: (r) => r.bank },
    { key: "provider", header: "Type", render: (r) => r.provider },
    {
      key: "income",
      header: "Income",
      align: "right",
      sortable: true,
      sortValue: (r) => r.income,
      render: (r) => <span className="text-emerald-400">+{fmt(r.income, r.currency)}</span>,
    },
    {
      key: "expenses",
      header: "Expenses",
      align: "right",
      sortable: true,
      sortValue: (r) => r.expenses,
      render: (r) => <span className="text-slate-400">−{fmt(r.expenses, r.currency)}</span>,
    },
    {
      key: "net",
      header: "Net",
      align: "right",
      sortable: true,
      sortValue: (r) => r.net,
      render: (r) => (
        <span className={r.net >= 0 ? "text-emerald-400" : "text-red-400"}>{fmt(r.net, r.currency)}</span>
      ),
    },
    {
      key: "txns",
      header: "Txns",
      align: "right",
      sortable: true,
      sortValue: (r) => r.transaction_count,
      render: (r) => r.transaction_count,
    },
  ];

  const categoryRows = data.category_spending.map((c, i) => ({ id: `cat-${i}`, ...c }));
  const monthRows = data.monthly_trend.map((m, i) => ({ id: `m-${i}`, ...m }));

  return (
    <div className="grid gap-5 lg:grid-cols-5">
      <div className="space-y-5 lg:col-span-3">
        <AnalyticsSection title="By account" description="Bank cash movement by connected account">
          <DataTable columns={bankCols} data={bankRows} searchKeys={["bank", "provider"]} pageSize={8} />
        </AnalyticsSection>

        <AnalyticsSection
          title={fromQb ? "Expense accounts (QuickBooks)" : "Category breakdown"}
          description={fromQb ? "Chart of accounts from posted books" : "Bank categories (pre-accounting)"}
        >
          <DataTable
            columns={[
              {
                key: "category",
                header: "Category",
                sortable: true,
                render: (r) => formatCategory(r.category),
                sortValue: (r) => r.category,
              },
              {
                key: "amount",
                header: "Amount",
                align: "right",
                sortable: true,
                sortValue: (r) => r.amount,
                render: (r) => fmt(r.amount),
              },
              {
                key: "pct",
                header: "Share",
                align: "right",
                sortable: true,
                sortValue: (r) => r.pct,
                render: (r) => `${r.pct}%`,
              },
            ]}
            data={categoryRows}
            pageSize={10}
          />
        </AnalyticsSection>
      </div>

      <div className="space-y-5 lg:col-span-2">
        <AnalyticsSection title="Monthly trend" description={fromQb ? "QuickBooks P&L by month" : "Bank cash by month"}>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data.monthly_trend}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="month" tick={{ fill: "#64748b", fontSize: 10 }} />
              <YAxis tick={{ fill: "#64748b", fontSize: 10 }} width={48} />
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155", fontSize: 12 }} />
              <Bar dataKey="income" fill="#22C55E" radius={[2, 2, 0, 0]} />
              <Bar dataKey="expenses" fill="#EF4444" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </AnalyticsSection>

        <AnalyticsSection title="Monthly detail" description="Full table">
          <DataTable
            dense
            pageSize={6}
            data={monthRows}
            columns={[
              { key: "month", header: "Month", sortable: true, render: (r) => r.month, sortValue: (r) => r.month },
              {
                key: "net",
                header: "Net",
                align: "right",
                sortable: true,
                sortValue: (r) => r.net,
                render: (r) => (
                  <span className={r.net >= 0 ? "text-emerald-400" : "text-red-400"}>{fmt(r.net)}</span>
                ),
              },
            ]}
          />
        </AnalyticsSection>
      </div>
    </div>
  );
}

function BankActivityView({ data, fmt }: { data: AnalysisData; fmt: Fmt }) {
  const act = data.bank_activity;
  const merchants = (act?.top_merchants ?? data.top_merchants).map((m, i) => ({ id: `m-${i}`, ...m }));
  const recurring = (act?.recurring_detected ?? data.recurring_detected).map((r, i) => ({ id: `r-${i}`, ...r }));
  const anomalies = (act?.anomalies ?? data.anomalies).map((a, i) => ({ id: `a-${i}`, ...a }));

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <AnalyticsSection
        title="Top merchants"
        description="Operational view from bank narrations (not QuickBooks P&L)"
        className="lg:col-span-2"
      >
        <DataTable
          data={merchants}
          searchKeys={["merchant"]}
          columns={[
            { key: "merchant", header: "Merchant", sortable: true, render: (r) => r.merchant, sortValue: (r) => r.merchant },
            { key: "amount", header: "Volume", align: "right", sortable: true, sortValue: (r) => r.amount, render: (r) => fmt(r.amount) },
            { key: "count", header: "Count", align: "right", sortable: true, sortValue: (r) => r.count, render: (r) => r.count },
          ]}
        />
      </AnalyticsSection>

      <AnalyticsSection title="Recurring detected" description="Subscription-like bank patterns">
        <DataTable
          data={recurring}
          columns={[
            { key: "name", header: "Name", sortable: true, render: (r) => r.name, sortValue: (r) => r.name },
            { key: "amount", header: "Amount", align: "right", sortable: true, sortValue: (r) => r.amount, render: (r) => fmt(r.amount, r.currency) },
            { key: "source", header: "Source", render: (r) => r.source },
          ]}
        />
      </AnalyticsSection>

      <AnalyticsSection title="Anomalies" description="Unusual bank activity">
        <DataTable
          data={anomalies}
          columns={[
            { key: "date", header: "Date", sortable: true, render: (r) => r.date, sortValue: (r) => r.date },
            { key: "counterparty", header: "Counterparty", render: (r) => r.counterparty },
            { key: "amount", header: "Amount", align: "right", sortable: true, sortValue: (r) => r.amount, render: (r) => fmt(r.amount, r.currency) },
            { key: "reason", header: "Reason", render: (r) => r.reason },
          ]}
        />
      </AnalyticsSection>
    </div>
  );
}

function SpendingView({ data, fmt, fromQb }: { data: AnalysisData; fmt: Fmt; fromQb: boolean }) {
  const merchants = data.top_merchants.map((m, i) => ({ id: `m-${i}`, ...m }));
  const channels = (data.spending_habits?.channel_mix ?? []).map((c, i) => ({ id: `ch-${i}`, ...c }));
  const drift = (data.spending_habits?.category_drift ?? []).map((c, i) => ({ id: `d-${i}`, ...c }));

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <AnalyticsSection title="Top merchants" description="Bank counterparty spend (see Bank activity tab)">
        <DataTable
          data={merchants}
          searchKeys={["merchant"]}
          columns={[
            { key: "merchant", header: "Merchant", sortable: true, render: (r) => r.merchant, sortValue: (r) => r.merchant },
            { key: "amount", header: "Spent", align: "right", sortable: true, sortValue: (r) => r.amount, render: (r) => fmt(r.amount) },
            { key: "count", header: "Count", align: "right", sortable: true, sortValue: (r) => r.count, render: (r) => r.count },
          ]}
        />
      </AnalyticsSection>

      <AnalyticsSection title="Channel mix" description="NIP, POS, web, etc.">
        <DataTable
          data={channels}
          emptyHint="Sync bank transactions to see channel data"
          columns={[
            { key: "channel", header: "Channel", sortable: true, render: (r) => r.channel, sortValue: (r) => r.channel },
            { key: "amount", header: "Amount", align: "right", sortable: true, sortValue: (r) => r.amount, render: (r) => fmt(r.amount) },
            { key: "pct", header: "Share", align: "right", sortable: true, sortValue: (r) => r.pct, render: (r) => `${r.pct}%` },
          ]}
        />
      </AnalyticsSection>

      <AnalyticsSection
        title="Weekday vs weekend"
        description={`Weekend share: ${data.spending_habits?.weekday_vs_weekend?.weekend_pct ?? 0}%`}
        className="lg:col-span-2"
      >
        <ResponsiveContainer width="100%" height={180}>
          <BarChart
            data={[
              { name: "Weekday", amount: data.spending_habits?.weekday_vs_weekend?.weekday ?? 0 },
              { name: "Weekend", amount: data.spending_habits?.weekday_vs_weekend?.weekend ?? 0 },
            ]}
          >
            <XAxis dataKey="name" tick={{ fill: "#94a3b8" }} />
            <YAxis tick={{ fill: "#94a3b8" }} />
            <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
            <Bar dataKey="amount" fill="#3B82F6" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </AnalyticsSection>

      <AnalyticsSection
        title="Category drift (MoM)"
        description={fromQb ? "QuickBooks expense accounts" : "Bank categories changing month over month"}
        className="lg:col-span-2"
      >
        <DataTable
          data={drift}
          columns={[
            { key: "category", header: "Category", sortable: true, render: (r) => formatCategory(r.category), sortValue: (r) => r.category },
            { key: "current", header: "Current", align: "right", sortable: true, sortValue: (r) => r.current, render: (r) => fmt(r.current) },
            { key: "previous", header: "Previous", align: "right", sortable: true, sortValue: (r) => r.previous, render: (r) => fmt(r.previous) },
            {
              key: "change",
              header: "Change",
              align: "right",
              sortable: true,
              sortValue: (r) => r.change_pct ?? 0,
              render: (r) => (r.change_pct != null ? <TrendBadge value={r.change_pct} /> : "—"),
            },
          ]}
        />
      </AnalyticsSection>
    </div>
  );
}

function IncomeView({ data, fmt, fromQb }: { data: AnalysisData; fmt: Fmt; fromQb: boolean }) {
  const runway = data.cash_runway.map((r, i) => ({ id: `r-${i}`, ...r }));
  const salary = (data.income_insights?.salary_candidates ?? []).map((s, i) => ({ id: `s-${i}`, ...s }));
  const yearly = data.yearly_trend.map((y, i) => ({ id: `y-${i}`, ...y }));

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <AnalyticsSection title="Cash runway" description="Days of runway per account">
        <DataTable
          data={runway}
          columns={[
            { key: "account", header: "Account", sortable: true, render: (r) => r.account_name, sortValue: (r) => r.account_name },
            { key: "balance", header: "Balance", align: "right", sortable: true, sortValue: (r) => r.balance, render: (r) => fmt(r.balance, r.currency) },
            { key: "burn", header: "Daily burn", align: "right", sortable: true, sortValue: (r) => r.avg_daily_net_burn, render: (r) => fmt(r.avg_daily_net_burn, r.currency) },
            { key: "days", header: "Days left", align: "right", sortable: true, sortValue: (r) => r.days_of_runway ?? 0, render: (r) => (r.days_of_runway != null ? r.days_of_runway : "—") },
          ]}
        />
      </AnalyticsSection>

      <AnalyticsSection title="Income candidates" description="Recurring salary-like credits">
        <DataTable
          data={salary}
          columns={[
            { key: "cp", header: "Counterparty", sortable: true, render: (r) => r.counterparty, sortValue: (r) => r.counterparty },
            { key: "avg", header: "Avg amount", align: "right", sortable: true, sortValue: (r) => r.avg_amount, render: (r) => fmt(r.avg_amount) },
            { key: "count", header: "Count", align: "right", sortable: true, sortValue: (r) => r.count, render: (r) => r.count },
          ]}
        />
      </AnalyticsSection>

      <AnalyticsSection title="Yearly trend" description={fromQb ? "QuickBooks P&L by year" : "Bank cash by year"} className="lg:col-span-2">
        <DataTable
          data={yearly}
          columns={[
            { key: "year", header: "Year", sortable: true, render: (r) => r.year, sortValue: (r) => r.year },
            { key: "income", header: "Income", align: "right", sortable: true, sortValue: (r) => r.income, render: (r) => <span className="text-emerald-400">+{fmt(r.income)}</span> },
            { key: "expenses", header: "Expenses", align: "right", sortable: true, sortValue: (r) => r.expenses, render: (r) => fmt(r.expenses) },
            { key: "net", header: "Net", align: "right", sortable: true, sortValue: (r) => r.net, render: (r) => <span className={r.net >= 0 ? "text-emerald-400" : "text-red-400"}>{fmt(r.net)}</span> },
          ]}
        />
      </AnalyticsSection>
    </div>
  );
}

function TransfersView({ data, fmt }: { data: AnalysisData; fmt: Fmt }) {
  const flows = data.counterparty_flows.map((c, i) => ({ id: `f-${i}`, ...c }));
  const top = (data.transfer_activity?.top_counterparties ?? []).map((c, i) => ({ id: `t-${i}`, ...c }));

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-3">
        <KpiCard label="Transfer in" value={fmt(data.transfer_activity?.transfer_in ?? 0)} accent="positive" />
        <KpiCard label="Transfer out" value={fmt(data.transfer_activity?.transfer_out ?? 0)} />
        <KpiCard label="Transfer count" value={data.transfer_activity?.count ?? 0} accent="neutral" />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <AnalyticsSection title="Counterparty flows" description="Sent vs received">
          <DataTable
            data={flows}
            searchKeys={["counterparty"]}
            columns={[
              { key: "cp", header: "Counterparty", sortable: true, render: (r) => r.counterparty, sortValue: (r) => r.counterparty },
              { key: "sent", header: "Sent", align: "right", sortable: true, sortValue: (r) => r.sent, render: (r) => fmt(r.sent) },
              { key: "recv", header: "Received", align: "right", sortable: true, sortValue: (r) => r.received, render: (r) => fmt(r.received) },
              { key: "net", header: "Net", align: "right", sortable: true, sortValue: (r) => r.net, render: (r) => <span className={r.net >= 0 ? "text-emerald-400" : "text-red-400"}>{fmt(r.net)}</span> },
            ]}
          />
        </AnalyticsSection>

        <AnalyticsSection title="Top transfer counterparties">
          <DataTable
            data={top}
            columns={[
              { key: "cp", header: "Counterparty", sortable: true, render: (r) => r.counterparty, sortValue: (r) => r.counterparty },
              { key: "vol", header: "Volume", align: "right", sortable: true, sortValue: (r) => r.volume, render: (r) => fmt(r.volume) },
              { key: "count", header: "Count", align: "right", sortable: true, sortValue: (r) => r.count, render: (r) => r.count },
            ]}
          />
        </AnalyticsSection>
      </div>
    </div>
  );
}

function CompareView({
  data,
  fmt,
  pc,
  fromQb,
}: {
  data: AnalysisData;
  fmt: Fmt;
  pc: typeof EMPTY_PERIOD;
  fromQb: boolean;
}) {
  const periodRows = [
    { id: "income", metric: fromQb ? "Revenue" : "Cash in", current: pc.current.income, previous: pc.previous.income, change: pc.income_change_pct },
    { id: "expenses", metric: fromQb ? "Expenses" : "Cash out", current: pc.current.expenses, previous: pc.previous.expenses, change: pc.expense_change_pct },
    { id: "net", metric: fromQb ? "Net profit" : "Net cash", current: pc.current.net, previous: pc.previous.net, change: pc.net_change_pct },
    { id: "xfer", metric: "Transfers (bank)", current: pc.current.transfer_volume, previous: pc.previous.transfer_volume, change: pc.transfer_volume_change_pct },
  ];

  return (
    <div className="space-y-5">
      <AnalyticsSection title={pc.label} description={fromQb ? "QuickBooks P&L period comparison" : "Bank cash comparison"}>
        <DataTable
          data={periodRows}
          columns={[
            { key: "metric", header: "Metric", render: (r) => r.metric },
            { key: "current", header: "Current", align: "right", render: (r) => fmt(r.current) },
            { key: "previous", header: "Previous", align: "right", render: (r) => fmt(r.previous) },
            { key: "change", header: "Change", align: "right", render: (r) => <TrendBadge value={r.change} /> },
          ]}
        />
      </AnalyticsSection>

      {data.account_comparison ? (
        <AnalyticsSection title="Account A vs B" description="Side-by-side account metrics">
          <DataTable
            data={data.account_comparison.category_diff.map((c, i) => ({ id: `cd-${i}`, ...c }))}
            columns={[
              { key: "cat", header: "Category", render: (r) => formatCategory(r.category) },
              { key: "a", header: "Account A", align: "right", sortable: true, sortValue: (r) => r.amount_a, render: (r) => fmt(r.amount_a) },
              { key: "b", header: "Account B", align: "right", sortable: true, sortValue: (r) => r.amount_b, render: (r) => fmt(r.amount_b) },
              { key: "delta", header: "Change", align: "right", render: (r) => (r.delta_pct != null ? <TrendBadge value={r.delta_pct} /> : "—") },
            ]}
          />
        </AnalyticsSection>
      ) : (
        <p className="rounded-lg border border-dashed border-slate-700 px-4 py-8 text-center text-sm text-slate-500">
          Open <strong className="text-slate-400">Advanced options</strong> in filters and pick Compare account A &amp; B.
        </p>
      )}

      <AnalyticsSection title="Daily net cash flow" description="Last 30 days">
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={data.daily_cashflow}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="date" tick={{ fill: "#64748b", fontSize: 10 }} />
            <YAxis tick={{ fill: "#64748b", fontSize: 10 }} width={48} />
            <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
            <Area type="monotone" dataKey="net" stroke="#3B82F6" fill="#3B82F630" />
          </AreaChart>
        </ResponsiveContainer>
      </AnalyticsSection>
    </div>
  );
}

function InsightsView({ data, fmt }: { data: AnalysisData; fmt: Fmt }) {
  const anomalies = data.anomalies.map((a, i) => ({ id: `a-${i}`, ...a }));
  const recurring = data.recurring_detected.map((r, i) => ({ id: `r-${i}`, ...r }));

  return (
    <div className="space-y-5">
      {data.insights.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2">
          {data.insights.map((ins, i) => (
            <div key={i} className="rounded-xl border border-slate-800/60 bg-slate-900/40 p-4">
              <div className="flex items-start justify-between gap-2">
                <p className="font-medium text-white">{ins.title}</p>
                <Badge variant="secondary" className="shrink-0 text-[10px] capitalize">
                  {ins.type}
                </Badge>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-slate-400">{ins.body}</p>
            </div>
          ))}
        </div>
      )}

      <AnalyticsSection title="Anomalies" description="Unusual transactions flagged">
        <DataTable
          data={anomalies}
          searchKeys={["counterparty", "reason"]}
          columns={[
            { key: "date", header: "Date", sortable: true, render: (r) => r.date, sortValue: (r) => r.date },
            { key: "cp", header: "Counterparty", sortable: true, render: (r) => r.counterparty, sortValue: (r) => r.counterparty },
            { key: "amt", header: "Amount", align: "right", sortable: true, sortValue: (r) => r.amount, render: (r) => fmt(r.amount, r.currency) },
            { key: "reason", header: "Reason", render: (r) => <span className="text-slate-400">{r.reason}</span> },
          ]}
        />
      </AnalyticsSection>

      <AnalyticsSection title="Detected recurring">
        <DataTable
          data={recurring}
          columns={[
            { key: "name", header: "Name", sortable: true, render: (r) => r.name, sortValue: (r) => r.name },
            { key: "amount", header: "Amount", align: "right", sortable: true, sortValue: (r) => r.amount, render: (r) => fmt(r.amount, r.currency) },
            { key: "source", header: "Source", render: (r) => r.source },
          ]}
        />
      </AnalyticsSection>
    </div>
  );
}
