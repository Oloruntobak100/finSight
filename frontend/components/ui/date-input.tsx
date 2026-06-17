"use client";

import * as React from "react";
import { Calendar } from "lucide-react";
import { cn } from "@/lib/utils";

export function DateInput({ className, ...props }: React.ComponentProps<"input">) {
  const inputRef = React.useRef<HTMLInputElement>(null);

  function openPicker() {
    const input = inputRef.current;
    if (!input) return;
    if (typeof input.showPicker === "function") {
      input.showPicker();
    } else {
      input.focus();
      input.click();
    }
  }

  return (
    <div className="relative">
      <input
        ref={inputRef}
        type="date"
        className={cn(
          "date-input flex h-10 w-full rounded-lg border border-slate-700 bg-slate-900/50 py-2 pl-3 pr-10 text-sm text-white placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
          className
        )}
        {...props}
      />
      <button
        type="button"
        tabIndex={-1}
        onClick={openPicker}
        className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-slate-300 hover:text-white"
        aria-label="Open calendar"
      >
        <Calendar className="h-4 w-4" />
      </button>
    </div>
  );
}
