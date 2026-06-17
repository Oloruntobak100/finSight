"use client";

import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";

const COLORS = ["#3B82F6", "#22C55E", "#EAB308", "#EF4444", "#8B5CF6", "#64748B"];

export function DashboardCharts({
  transactions,
}: {
  transactions: Array<{ category?: string; amount: number; transaction_type: string }>;
}) {
  const byCategory: Record<string, number> = {};
  transactions
    .filter((t) => t.transaction_type === "debit")
    .forEach((t) => {
      const cat = t.category || "Other";
      byCategory[cat] = (byCategory[cat] || 0) + t.amount;
    });

  const data = Object.entries(byCategory).map(([name, value]) => ({ name, value }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Spending by Category</CardTitle>
      </CardHeader>
      {data.length === 0 ? (
        <p className="text-sm text-slate-500">No spending data yet</p>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label>
              {data.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}
