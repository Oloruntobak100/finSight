import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-slate-800/70", className)}
      aria-hidden
    />
  );
}

export function TableRowSkeleton({ cols = 6 }: { cols?: number }) {
  return (
    <tr className="border-b border-slate-800/50">
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="py-3">
          <Skeleton className={`h-4 ${i === cols - 1 ? "ml-auto w-16" : "w-full max-w-[120px]"}`} />
        </td>
      ))}
    </tr>
  );
}
