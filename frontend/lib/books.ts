import { apiFetch, BOOKS_APPROVE_TIMEOUT_MS, BOOKS_BULK_APPROVE_TIMEOUT_MS, BOOKS_CLASSIFY_TIMEOUT_MS, type ApiFetchOptions } from "@/lib/api";

export type QbSyncStatus =
  | "pending"
  | "needs_review"
  | "posted"
  | "excluded"
  | "failed"
  | "skipped"
  | "auto_approved"
  | "unclassified";

export type RevertTarget = "needs_review" | "unclassified";

export type SuggestionMethod =
  | "rule"
  | "fingerprint"
  | "rag"
  | "llm"
  | "auto"
  | "manual"
  | "auto_detect"
  | "category";

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
  qb_party_id?: string | null;
  qb_party_type?: "Vendor" | "Customer" | null;
  qb_party_name?: string | null;
  qb_posting_type?: string | null;
  qb_entity_id?: string | null;
  qb_doc_number?: string | null;
  qb_posted_at?: string | null;
  qb_error?: string | null;
}

export type QbPartyType = "Vendor" | "Customer";

export interface QbParty {
  id: string;
  qb_party_id: string;
  display_name: string;
  party_type: QbPartyType;
  active: boolean;
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

export interface BooksCoverage {
  total_bank_transactions: number;
  classified: number;
  unclassified: number;
}

export interface BooksSummary {
  counts: Record<string, number>;
  coverage?: BooksCoverage;
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

export async function syncCoa(): Promise<{ synced: number; removed?: number; realm_id?: string }> {
  return apiFetch("/books/coa/sync", { method: "POST" });
}

export async function listCoa(
  accountType?: string,
  fresh = false
): Promise<{ items: CoaAccount[]; total: number }> {
  const params = new URLSearchParams();
  if (accountType) params.set("account_type", accountType);
  if (fresh) params.set("fresh", "true");
  const q = params.toString() ? `?${params.toString()}` : "";
  return apiFetch(`/books/coa${q}`);
}

export async function listQbParties(fresh = false): Promise<{ vendors: QbParty[]; customers: QbParty[] }> {
  const q = fresh ? "?fresh=true" : "";
  return apiFetch(`/books/parties${q}`);
}

export async function createQbParty(
  displayName: string,
  partyType: QbPartyType
): Promise<{ qb_party_id: string; qb_party_type: QbPartyType; qb_party_name: string }> {
  return apiFetch("/books/parties", {
    method: "POST",
    body: JSON.stringify({ display_name: displayName, party_type: partyType }),
    timeoutMs: BOOKS_APPROVE_TIMEOUT_MS,
  });
}

export async function suggestQbParty(
  transactionId: string,
  accountId: string
): Promise<{ qb_party_id: string; qb_party_type: QbPartyType; qb_party_name?: string; match_score: number }> {
  const params = new URLSearchParams({ transaction_id: transactionId, account_id: accountId });
  return apiFetch(`/books/parties/suggest?${params}`);
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
): Promise<{ classified: number; remaining_unclassified: number }> {
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
  post = true,
  party?: { id: string; type: QbPartyType }
): Promise<{ approved: boolean; similar_updated?: number }> {
  return apiFetch("/books/approve", {
    method: "POST",
    body: JSON.stringify({
      transaction_id: transactionId,
      final_account_id: finalAccountId,
      post,
      final_party_id: party?.id ?? null,
      final_party_type: party?.type ?? null,
    }),
    timeoutMs: BOOKS_APPROVE_TIMEOUT_MS,
  });
}

export interface BulkApproveItem {
  transaction_id: string;
  final_account_id: string;
  final_party_id?: string;
  final_party_type?: QbPartyType;
}

export async function approveBulk(body: {
  items?: BulkApproveItem[];
  transaction_ids?: string[];
  payee_pattern?: string;
  final_account_id?: string;
  post?: boolean;
}): Promise<{
  approved: number;
  failed: number;
  similar_updated?: number;
  errors: { transaction_id: string; error: string }[];
}> {
  const count = body.items?.length ?? body.transaction_ids?.length ?? 0;
  const timeoutMs = count > 3 ? BOOKS_BULK_APPROVE_TIMEOUT_MS : BOOKS_APPROVE_TIMEOUT_MS;
  return apiFetch("/books/approve/bulk", {
    method: "POST",
    body: JSON.stringify(body),
    timeoutMs,
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
    timeoutMs: BOOKS_APPROVE_TIMEOUT_MS,
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

export async function revertTransaction(
  transactionId: string,
  target: RevertTarget
): Promise<{ transaction_id: string; previous_status?: string; target: RevertTarget }> {
  return apiFetch("/books/revert", {
    method: "POST",
    body: JSON.stringify({ transaction_id: transactionId, target }),
    timeoutMs: BOOKS_APPROVE_TIMEOUT_MS,
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

export type ReconciliationSide = "debit" | "credit" | "all";

export interface ReconciliationBankOption {
  id: string;
  account_name: string;
  provider: string;
  qb_account_id?: string | null;
  qb_account_name?: string | null;
}

export interface ReconciliationOptions {
  bank_accounts: ReconciliationBankOption[];
  qb_bank_accounts: { qb_account_id: string; name: string }[];
}

export interface ReconciliationRunParams {
  periodStart?: string;
  periodEnd?: string;
  bankAccountId?: string;
  qbBankAccountId?: string;
  transactionSide?: ReconciliationSide;
}

export async function getReconciliationOptions(): Promise<ReconciliationOptions> {
  return apiFetch("/reconciliation/options");
}

export async function runReconciliation(params: ReconciliationRunParams = {}): Promise<unknown> {
  return apiFetch("/reconciliation/run", {
    method: "POST",
    body: JSON.stringify({
      period_start: params.periodStart ?? null,
      period_end: params.periodEnd ?? null,
      bank_account_id: params.bankAccountId ?? null,
      qb_bank_account_id: params.qbBankAccountId ?? null,
      transaction_side: params.transactionSide ?? "debit",
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
