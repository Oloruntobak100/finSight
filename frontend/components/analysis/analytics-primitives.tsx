import { cn } from "@/lib/utils";

interface KpiCardProps {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  trend?: React.ReactNode;
  accent?: "default" | "positive" | "negative" | "neutral";
}

const accentStyles = {
  default: "text-white",
  positive: "text-emerald-400",
  negative: "text-red-400",
  neutral: "text-slate-200",
};

export function KpiCard({ label, value, sub, trend, accent = "default" }: KpiCardProps) {
  return (
    <div className="rounded-xl border border-slate-800/70 bg-gradient-to-br from-slate-900/80 to-slate-950/40 p-4">
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={cn("mt-1.5 text-2xl font-bold tabular-nums", accentStyles[accent])}>{value}</p>
      {(sub || trend) && (
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          {sub}
          {trend}
        </div>
      )}
    </div>
  );
}

interface AnalyticsSectionProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

export function AnalyticsSection({ title, description, action, children, className }: AnalyticsSectionProps) {
  return (
    <section className={cn("rounded-xl border border-slate-800/60 bg-slate-950/30", className)}>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-800/50 px-5 py-4">
        <div>
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          {description && <p className="mt-0.5 text-xs text-slate-500">{description}</p>}
        </div>
        {action}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}
