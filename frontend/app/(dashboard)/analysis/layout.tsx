import { Suspense } from "react";
import { AnalyticsViewNav } from "@/components/analysis/analytics-view-nav";
import { Skeleton } from "@/components/ui/skeleton";

export default function AnalysisLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="space-y-5">
      <Suspense fallback={<Skeleton className="h-10 w-full rounded-lg" />}>
        <AnalyticsViewNav />
      </Suspense>
      {children}
    </div>
  );
}
