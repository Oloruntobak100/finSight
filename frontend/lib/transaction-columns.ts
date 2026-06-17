export type TransactionColumnId =
  | "date"
  | "bank"
  | "type"
  | "direction"
  | "counterparty"
  | "channel"
  | "category"
  | "reference"
  | "narration"
  | "amount";

export interface TransactionColumnDef {
  id: TransactionColumnId;
  label: string;
  defaultVisible: boolean;
  required?: boolean;
}

export const TRANSACTION_COLUMNS: TransactionColumnDef[] = [
  { id: "date", label: "Date", defaultVisible: true, required: true },
  { id: "bank", label: "Bank", defaultVisible: true },
  { id: "type", label: "Type", defaultVisible: true },
  { id: "direction", label: "Direction", defaultVisible: false },
  { id: "counterparty", label: "Counterparty", defaultVisible: true },
  { id: "channel", label: "Channel", defaultVisible: false },
  { id: "category", label: "Category", defaultVisible: true },
  { id: "reference", label: "Reference", defaultVisible: false },
  { id: "narration", label: "Narration", defaultVisible: false },
  { id: "amount", label: "Amount", defaultVisible: true, required: true },
];

export const TRANSACTION_COLUMNS_STORAGE_KEY = "finsight-transaction-columns";

export function getDefaultVisibleColumns(): Record<TransactionColumnId, boolean> {
  return Object.fromEntries(
    TRANSACTION_COLUMNS.map((col) => [col.id, col.defaultVisible])
  ) as Record<TransactionColumnId, boolean>;
}

export function loadVisibleColumns(): Record<TransactionColumnId, boolean> {
  const defaults = getDefaultVisibleColumns();
  if (typeof window === "undefined") return defaults;

  try {
    const raw = localStorage.getItem(TRANSACTION_COLUMNS_STORAGE_KEY);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw) as Partial<Record<TransactionColumnId, boolean>>;
    const merged = { ...defaults };
    for (const col of TRANSACTION_COLUMNS) {
      if (typeof parsed[col.id] === "boolean") {
        merged[col.id] = parsed[col.id]!;
      }
    }
    for (const col of TRANSACTION_COLUMNS) {
      if (col.required) merged[col.id] = true;
    }
    return merged;
  } catch {
    return defaults;
  }
}

export function saveVisibleColumns(visible: Record<TransactionColumnId, boolean>) {
  if (typeof window === "undefined") return;
  const payload = { ...visible };
  for (const col of TRANSACTION_COLUMNS) {
    if (col.required) payload[col.id] = true;
  }
  localStorage.setItem(TRANSACTION_COLUMNS_STORAGE_KEY, JSON.stringify(payload));
}
