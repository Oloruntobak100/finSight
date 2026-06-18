import { apiFetch } from "@/lib/api";

export type QbSyncStatus =
  | "pending"
  | "needs_review"
  | "posted"
  | "excluded"
  | "failed"
  | "skipped";

export interface CoaAccount {
  id: string;
  qb_account_id: string;
  name: string;
  account_type?: string | null;
  account_sub_type?: string | null;
  active: boolean;
}

export interface AccountMapping {
  id?: string;
  mapping_type: "bank_account" | "category";
  finsight_key: string;
  qb_account_id: string;
  qb_account_name?: string | null;
}

export interface QueueItem {
  id: string;
  transaction_date: string;
  merchant_name?: string | null;
  description?: string | null;
  category?: string | null;
  amount: number;
  currency: string;
  transaction_type: string;
  account_id?: string | null;
  account_name?: string | null;
  qb_sync_status?: QbSyncStatus | null;
  qb_account_id?: string | null;
  qb_account_name?: string | null;
  qb_payment_account_id?: string | null;
  qb_confidence?: number | null;
  qb_posting_type?: string | null;
  qb_entity_id?: string | null;
  qb_posted_at?: string | null;
  qb_error?: string | null;
}

export interface QueueList {
  items: QueueItem[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface BooksSummary {
  counts: Record<string, number>;
}

export interface QuickBooksStatus {
  connected: boolean;
  account_name?: string;
  expired?: boolean;
}

export async function getQuickBooksStatus(): Promise<QuickBooksStatus> {
  return apiFetch<QuickBooksStatus>("/oauth/quickbooks/status");
}

export async function syncCoa(): Promise<{ synced: number; realm_id?: string }> {
  return apiFetch("/books/coa/sync", { method: "POST" });
}

export async function listCoa(accountType?: string): Promise<{ items: CoaAccount[]; total: number }> {
  const q = accountType ? `?account_type=${encodeURIComponent(accountType)}` : "";
  return apiFetch(`/books/coa${q}`);
}

export async function listMappings(): Promise<AccountMapping[]> {
  return apiFetch("/books/mappings");
}

export async function upsertMapping(body: Omit<AccountMapping, "id">): Promise<AccountMapping> {
  return apiFetch("/books/mappings", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function classifyTransactions(transactionIds?: string[]): Promise<{ classified: number }> {
  return apiFetch("/books/classify", {
    method: "POST",
    body: JSON.stringify({ transaction_ids: transactionIds ?? null }),
  });
}

export async function getBooksQueue(
  status?: QbSyncStatus,
  page = 1,
  limit = 20
): Promise<QueueList> {
  const params = new URLSearchParams({ page: String(page), limit: String(limit) });
  if (status) params.set("status", status);
  return apiFetch(`/books/queue?${params}`);
}

export async function getBooksSummary(): Promise<BooksSummary> {
  return apiFetch("/books/summary");
}

export async function postTransaction(transactionId: string): Promise<unknown> {
  return apiFetch("/books/post", {
    method: "POST",
    body: JSON.stringify({ transaction_id: transactionId }),
  });
}

export async function postTransactionsBulk(transactionIds: string[]): Promise<{
  posted: number;
  skipped: number;
  failed: number;
  errors: { transaction_id: string; error: string }[];
}> {
  return apiFetch("/books/post/bulk", {
    method: "POST",
    body: JSON.stringify({ transaction_ids: transactionIds }),
  });
}

export async function excludeTransaction(transactionId: string): Promise<unknown> {
  return apiFetch("/books/exclude", {
    method: "POST",
    body: JSON.stringify({ transaction_id: transactionId }),
  });
}
