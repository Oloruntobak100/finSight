"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { formatCategory, formatCurrency } from "@/lib/utils";

export function DashboardCharts({
  transactions,
  currency = "NGN",
}: {
  transactions: Array<{ category?: string; amount: number; transaction_type: string }>;
  currency?: string;
}) {
  const byCategory: Record<string, number> = {};
  transactions
    .filter((t) => t.transaction_type === "debit")
    .forEach((t) => {
      const cat = t.category || "Other";
      byCategory[cat] = (byCategory[cat] || 0) + t.amount;
    });

  const data = Object.entries(byCategory)
    .map(([name, value]) => ({ name: formatCategory(name), value: Math.round(value * 100) / 100 }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 10);

  const chartHeight = Math.max(260, data.length * 36);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Spending by Category</CardTitle>
      </CardHeader>
      {data.length === 0 ? (
        <p className="px-6 pb-6 text-sm text-slate-500">No spending data yet</p>
      ) : (
        <div className="px-2 pb-4">
          <ResponsiveContainer width="100%" height={chartHeight}>
            <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
              <XAxis
                type="number"
                tick={{ fill: "#64748b", fontSize: 11 }}
                tickFormatter={(v) => {
                  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
                  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
                  return String(v);
                }}
              />
              <YAxis
                type="category"
                dataKey="name"
                width={120}
                tick={{ fill: "#94a3b8", fontSize: 11 }}
              />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #334155", fontSize: 12 }}
                formatter={(value: number) => formatCurrency(value, currency)}
              />
              <Bar dataKey="value" fill="#3B82F6" radius={[0, 4, 4, 0]} maxBarSize={28} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
