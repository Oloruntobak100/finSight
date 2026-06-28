import { apiFetch } from "@/lib/api";
import {
  getDefaultVisibleColumns,
  normalizeVisibleColumns,
  type TransactionColumnId,
} from "@/lib/transaction-columns";

export async function fetchUiPreferences(): Promise<Record<string, unknown>> {
  const data = await apiFetch<{ ui_preferences: Record<string, unknown> }>(
    "/users/ui-preferences"
  );
  return data.ui_preferences ?? {};
}

export async function saveUiPreferences(
  patch: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const data = await apiFetch<{ ui_preferences: Record<string, unknown> }>(
    "/users/ui-preferences",
    {
      method: "PATCH",
      body: JSON.stringify({ ui_preferences: patch }),
    }
  );
  return data.ui_preferences ?? {};
}

export function parseTransactionColumns(
  prefs: Record<string, unknown>
): Record<TransactionColumnId, boolean> {
  const defaults = getDefaultVisibleColumns();
  const raw = prefs.transaction_columns;
  if (!raw || typeof raw !== "object") return defaults;
  const parsed = raw as Partial<Record<TransactionColumnId, boolean>>;
  const merged = { ...defaults };
  for (const col of Object.keys(defaults) as TransactionColumnId[]) {
    if (typeof parsed[col] === "boolean") {
      merged[col] = parsed[col]!;
    }
  }
  return normalizeVisibleColumns(merged);
}

export async function loadTransactionColumnsFromServer(): Promise<
  Record<TransactionColumnId, boolean>
> {
  try {
    const prefs = await fetchUiPreferences();
    return parseTransactionColumns(prefs);
  } catch {
    return getDefaultVisibleColumns();
  }
}

export async function saveTransactionColumnsToServer(
  visible: Record<TransactionColumnId, boolean>
): Promise<void> {
  try {
    await saveUiPreferences({ transaction_columns: normalizeVisibleColumns(visible) });
  } catch {
    /* non-blocking */
  }
}
