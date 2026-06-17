"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { formatCurrency } from "@/lib/utils";

interface Subscription {
  merchant_name: string;
  amount: number;
  currency: string;
  frequency: string;
  annual_cost: number;
}

export default function SubscriptionsPage() {
  const [items, setItems] = useState<Subscription[]>([]);
  const [totalMonthly, setTotalMonthly] = useState(0);
  const [totalAnnual, setTotalAnnual] = useState(0);

  useEffect(() => {
    apiFetch<{ items: Subscription[]; total_monthly: number; total_annual: number }>(
      "/analytics/subscriptions"
    )
      .then((data) => {
        setItems(data.items);
        setTotalMonthly(data.total_monthly);
        setTotalAnnual(data.total_annual);
      })
      .catch(() => {});
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Subscriptions</h1>
        <p className="text-slate-400">Recurring charges detected from your transactions</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Monthly Burden</CardTitle>
          </CardHeader>
          <p className="text-3xl font-bold text-white">{formatCurrency(totalMonthly)}</p>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Annual Burden</CardTitle>
          </CardHeader>
          <p className="text-3xl font-bold text-white">{formatCurrency(totalAnnual)}</p>
        </Card>
      </div>

      <Card>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-left text-slate-400">
              <th className="pb-2">Merchant</th>
              <th className="pb-2">Amount</th>
              <th className="pb-2">Frequency</th>
              <th className="pb-2 text-right">Annual Cost</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td colSpan={4} className="py-8 text-center text-slate-500">
                  No recurring subscriptions detected yet
                </td>
              </tr>
            ) : (
              items.map((s) => (
                <tr key={s.merchant_name} className="border-b border-slate-800/50">
                  <td className="py-3 text-white">{s.merchant_name}</td>
                  <td className="py-3 text-slate-300">{formatCurrency(s.amount, s.currency)}</td>
                  <td className="py-3 text-slate-400 capitalize">{s.frequency}</td>
                  <td className="py-3 text-right text-white">{formatCurrency(s.annual_cost, s.currency)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
