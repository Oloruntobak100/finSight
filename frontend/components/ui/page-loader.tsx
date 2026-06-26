import { cn } from "@/lib/utils";

interface PageLoaderProps {
  message?: string;
  className?: string;
  /** full = centered page block; inline = table/content area; compact = overlay chip */
  variant?: "full" | "inline" | "compact";
}

export function LoaderIcon({ className }: { className?: string }) {
  return (
    <div className={cn("page-loader-orbit page-loader-orbit--sm shrink-0", className)} aria-hidden>
      <div className="page-loader-ring page-loader-ring--outer" />
      <div className="page-loader-ring page-loader-ring--mid" />
      <div className="page-loader-ring page-loader-ring--inner" />
      <div className="page-loader-core" />
    </div>
  );
}

export function PageLoader({
  message = "Loading…",
  className,
  variant = "full",
}: PageLoaderProps) {
  const isCompact = variant === "compact";

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center",
        variant === "full" && "min-h-[280px] gap-5 py-16",
        variant === "inline" && "min-h-[200px] gap-4 py-12",
        variant === "compact" && "gap-0",
        className
      )}
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div
        className={cn("page-loader-orbit", isCompact && "page-loader-orbit--sm")}
        aria-hidden
      >
        <div className="page-loader-ring page-loader-ring--outer" />
        <div className="page-loader-ring page-loader-ring--mid" />
        <div className="page-loader-ring page-loader-ring--inner" />
        <div className="page-loader-core" />
      </div>
      {message && !isCompact && (
        <p className="text-sm font-medium tracking-wide text-slate-400">{message}</p>
      )}
      {(message || isCompact) && <span className="sr-only">{message || "Loading"}</span>}
    </div>
  );
}
