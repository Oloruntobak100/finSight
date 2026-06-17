"use client";

import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import {
  getDefaultVisibleColumns,
  TRANSACTION_COLUMNS,
  type TransactionColumnId,
} from "@/lib/transaction-columns";

interface ColumnPickerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  visible: Record<TransactionColumnId, boolean>;
  onChange: (visible: Record<TransactionColumnId, boolean>) => void;
}

export function ColumnPicker({ open, onOpenChange, visible, onChange }: ColumnPickerProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    function handleClick(event: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) {
        onOpenChange(false);
      }
    }

    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") onOpenChange(false);
    }

    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open, onOpenChange]);

  function toggleColumn(id: TransactionColumnId) {
    const col = TRANSACTION_COLUMNS.find((c) => c.id === id);
    if (col?.required) return;
    onChange({ ...visible, [id]: !visible[id] });
  }

  function showAll() {
    onChange(
      Object.fromEntries(TRANSACTION_COLUMNS.map((col) => [col.id, true])) as Record<
        TransactionColumnId,
        boolean
      >
    );
  }

  function resetDefaults() {
    onChange(getDefaultVisibleColumns());
  }

  const visibleCount = TRANSACTION_COLUMNS.filter((col) => visible[col.id]).length;

  return (
    <div ref={panelRef} className="relative">
      <Button
        variant="outline"
        size="sm"
        onClick={() => onOpenChange(!open)}
        aria-expanded={open}
        aria-haspopup="true"
      >
        Columns ({visibleCount})
      </Button>

      {open && (
        <div className="absolute right-0 z-20 mt-2 w-56 rounded-lg border border-slate-700 bg-slate-950 p-3 shadow-xl">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-400">
            Show columns
          </p>
          <div className="max-h-72 space-y-1 overflow-y-auto">
            {TRANSACTION_COLUMNS.map((col) => (
              <label
                key={col.id}
                className={`flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm ${
                  col.required ? "text-slate-500" : "text-slate-200 hover:bg-slate-900"
                }`}
              >
                <input
                  type="checkbox"
                  checked={visible[col.id]}
                  disabled={col.required}
                  onChange={() => toggleColumn(col.id)}
                  className="rounded border-slate-600 bg-slate-900"
                />
                <span>{col.label}</span>
              </label>
            ))}
          </div>
          <div className="mt-3 flex gap-2 border-t border-slate-800 pt-3">
            <button
              type="button"
              onClick={showAll}
              className="text-xs text-blue-400 hover:text-blue-300"
            >
              Show all
            </button>
            <button
              type="button"
              onClick={resetDefaults}
              className="text-xs text-slate-400 hover:text-slate-300"
            >
              Reset
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
