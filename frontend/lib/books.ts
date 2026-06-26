import { apiFetch, BOOKS_CLASSIFY_TIMEOUT_MS, type ApiFetchOptions } from "@/lib/api";

export type QbSyncStatus =
  | "pending"
  | "needs_review"
  | "posted"
  | "excluded"
  | "failed"
  | "skipped"
  | "auto_approved";

export type SuggestionMethod = "rule" | "fingerprint" | "rag" | "llm" | "auto" | "manual";

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
  payee_pattern?: string | null;
  posting_intent?: string | null;
  qb_sync_status?: QbSyncStatus | null;
  qb_account_id?: string | null;
  qb_account_name?: string | null;
  qb_payment_account_id?: string | null;
  qb_confidence?: number | null;
  qb_suggestion_method?: SuggestionMethod | null;
  qb_confidence_reason?: string | null;
  qb_posting_type?: string | null;
  qb_entity_id?: string | null;
  qb_posted_at?: string | null;
  qb_error?: string | null;
}

export interface QueueGroup {
  payee_pattern: string;
  count: number;
  total_amount: number;
  qb_account_id?: string | null;
  qb_account_name?: string | null;
  qb_confidence?: number | null;
  qb_suggestion_method?: string | null;
  transaction_ids: string[];
}

export interface QueueList {
  items: QueueItem[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface BooksReadiness {
  qb_connected: boolean;
  bank_connected: boolean;
  bank_accounts: Array<{
    id: string;
    account_name?: string | null;
    provider?: string;
    last_synced_at?: string | null;
  }>;
  qb_environment?: string | null;
  qb_account_name?: string | null;
}

export interface BooksSummary {
  counts: Record<string, number>;
  automation?: AutomationSettings;
  readiness?: BooksReadiness;
}

export interface AutomationSettings {
  auto_approve_enabled: boolean;
  auto_approve_threshold: number;
  digest_enabled: boolean;
}

export interface QuickBooksStatus {
  connected: boolean;
  account_name?: string;
  expired?: boolean;
  environment?: string;
}

export interface LearningProgressItem {
  payee_pattern: string;
  account_name?: string | null;
  qb_account_id?: string | null;
  transaction_count?: number;
  avg_confidence: number;
  auto_approve_eligible: boolean;
  status: string;
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

export async function classifyTransactions(
  transactionIds?: string[],
  options?: Pick<ApiFetchOptions, "timeoutMs">
): Promise<{ classified: number }> {
  return apiFetch("/books/classify", {
    method: "POST",
    body: JSON.stringify({ transaction_ids: transactionIds ?? null }),
    timeoutMs: options?.timeoutMs ?? BOOKS_CLASSIFY_TIMEOUT_MS,
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

export async function getBooksGroups(status: QbSyncStatus = "pending"): Promise<QueueGroup[]> {
  return apiFetch(`/books/groups?status=${status}`);
}

export async function getBooksSummary(): Promise<BooksSummary> {
  return apiFetch("/books/summary");
}

export async function approveTransaction(
  transactionId: string,
  finalAccountId: string,
  post = true
): Promise<unknown> {
  return apiFetch("/books/approve", {
    method: "POST",
    body: JSON.stringify({
      transaction_id: transactionId,
      final_account_id: finalAccountId,
      post,
    }),
  });
}

export async function approveBulk(body: {
  transaction_ids?: string[];
  payee_pattern?: string;
  final_account_id?: string;
  post?: boolean;
}): Promise<{ approved: number; errors: { transaction_id: string; error: string }[] }> {
  return apiFetch("/books/approve/bulk", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function setPostingIntent(
  transactionId: string,
  intent: "expense" | "income" | "transfer" | "personal" | "fee"
): Promise<unknown> {
  return apiFetch("/books/intent", {
    method: "POST",
    body: JSON.stringify({ transaction_id: transactionId, intent }),
  });
}

export async function rejectSuggestion(transactionId: string): Promise<unknown> {
  return apiFetch("/books/reject", {
    method: "POST",
    body: JSON.stringify({ transaction_id: transactionId }),
  });
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

export async function getAutomationSettings(): Promise<AutomationSettings> {
  return apiFetch("/users/automation");
}

export async function updateAutomationSettings(
  patch: Partial<AutomationSettings>
): Promise<AutomationSettings> {
  return apiFetch("/users/automation", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function getLearningProgress(): Promise<{
  items: LearningProgressItem[];
  automation: AutomationSettings;
}> {
  return apiFetch("/users/learning-progress");
}

export async function runReconciliation(periodStart?: string, periodEnd?: string): Promise<unknown> {
  return apiFetch("/reconciliation/run", {
    method: "POST",
    body: JSON.stringify({
      period_start: periodStart ?? null,
      period_end: periodEnd ?? null,
    }),
  });
}

export async function fetchQbPnl(
  startDate: string,
  endDate: string,
  refresh = false
): Promise<unknown> {
  const params = new URLSearchParams({
    start_date: startDate,
    end_date: endDate,
    refresh: String(refresh),
  });
  return apiFetch(`/qb-reports/pnl?${params}`);
}
