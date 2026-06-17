"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

function sendLog(message: string, data: Record<string, unknown>, hypothesisId: string) {
  // #region agent log
  fetch("http://127.0.0.1:7668/ingest/c32e83b6-a8a1-4f0b-a657-6d851abe8926", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "8b2c82" },
    body: JSON.stringify({
      sessionId: "8b2c82",
      location: "chunk-debug.tsx",
      message,
      data,
      hypothesisId,
      timestamp: Date.now(),
      runId: "pre-fix",
    }),
  }).catch(() => {});
  // #endregion
}

export function ChunkDebugMonitor() {
  const pathname = usePathname();

  useEffect(() => {
    sendLog("route mounted", { pathname, href: window.location.href }, "B");

    const onError = (event: ErrorEvent) => {
      sendLog(
        "window error",
        {
          pathname,
          message: event.message,
          filename: event.filename,
          lineno: event.lineno,
          colno: event.colno,
        },
        "A"
      );
    };

    const onRejection = (event: PromiseRejectionEvent) => {
      const reason = event.reason;
      sendLog(
        "unhandled rejection",
        {
          pathname,
          reason:
            reason instanceof Error
              ? { name: reason.name, message: reason.message, stack: reason.stack?.slice(0, 500) }
              : String(reason),
        },
        "C"
      );
    };

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);

    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, [pathname]);

  return null;
}
