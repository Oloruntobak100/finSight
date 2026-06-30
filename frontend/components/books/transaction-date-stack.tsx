"use client";

function formatTxnDate(dateStr: string): string {
  const d = new Date(`${dateStr.slice(0, 10)}T12:00:00`);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatPostedDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export interface TransactionDateStackProps {
  transactionDate: string;
  postedDate?: string | null;
  postingLagDays?: number | null;
  unposted?: boolean;
  className?: string;
}

export function TransactionDateStack({
  transactionDate,
  postedDate,
  postingLagDays,
  unposted = false,
  className = "",
}: TransactionDateStackProps) {
  const lag = postingLagDays ?? (postedDate && transactionDate
    ? Math.max(
        0,
        Math.floor(
          (new Date(postedDate).getTime() - new Date(`${transactionDate.slice(0, 10)}T12:00:00`).getTime()) /
            86400000
        )
      )
    : null);

  const showPosted = !unposted && postedDate && (lag ?? 0) > 1;
  const showBacklogHint = !unposted && (lag ?? 0) > 7;

  return (
    <div className={`min-w-0 ${className}`}>
      <div className="text-sm font-medium text-white tabular-nums">
        {formatTxnDate(transactionDate)}
        {unposted && (
          <span className="ml-1.5 text-xs font-normal text-amber-400/90">· Awaiting review</span>
        )}
      </div>
      {showPosted && (
        <div className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500">
          <span>Posted {formatPostedDate(postedDate!)}</span>
          {showBacklogHint && (
            <span
              className="inline-block h-1.5 w-1.5 rounded-full bg-amber-400/80"
              title={`Reviewed ${lag} days after transaction`}
            />
          )}
        </div>
      )}
    </div>
  );
}
