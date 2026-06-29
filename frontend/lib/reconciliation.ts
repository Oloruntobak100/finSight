import { apiFetch } from "@/lib/api";

export type RunStatus = "DRAFT" | "IN_REVIEW" | "ADJUSTED" | "APPROVED" | "LOCKED";

export interface ReconciliationBankOption {
  id: string;
  account_name: string;
  provider: string;
  qb_account_id?: string | null;
  qb_account_name?: string | null;
}

export interface ReconciliationSetup {
  bank_accounts: ReconciliationBankOption[];
  qb_bank_accounts: { qb_account_id: string; name: string }[];
  default_period_start: string;
  default_period_end: string;
}

export interface BalancePreview {
  mono_closing_balance: number;
  mono_balance_source: string;
  qbo_book_balance: number;
  currency: string;
  raw_variance: number;
}

export interface ReconciliationRun {
  id: string;
  status: RunStatus;
  period_start: string;
  period_end: string;
  mono_account_id?: string;
  qb_bank_account_id?: string;
  mono_closing_balance?: number;
  qbo_book_balance?: number;
  variance?: number;
  self_approved?: boolean;
  summary?: {
    counts?: Record<string, number>;
    balance_proof?: BalanceProof;
    mono_line_count?: number;
    qbo_line_count?: number;
    currency?: string;
  };
  balance_proof?: BalanceProof;
}

export interface BalanceProof {
  mono_closing_balance: number;
  deposits_in_transit: number;
  outstanding_payments: number;
  bank_adjustments: number;
  adjusted_bank_balance: number;
  qbo_book_balance: number;
  unrecorded_bank_charges: number;
  unrecorded_bank_credits: number;
  book_adjustments: number;
  adjusted_book_balance: number;
  variance: number;
}

export interface ReconciliationItem {
  id: string;
  source: "MONO" | "QBO" | "BOTH";
  match_status: string;
  match_score?: number;
  amount: number;
  currency: string;
  transaction_date?: string;
  direction?: string;
  payee?: string;
  narration?: string;
  reference?: string;
  mono_transaction_id?: string;
  qbo_entity_id?: string;
  qbo_entity_type?: string;
}

export interface ReconciliationAdjustment {
  id: string;
  adjustment_type: string;
  affects_side: string;
  amount: number;
  description?: string;
  journal_entry_required: boolean;
  journal_entry_posted: boolean;
  journal_entry_id?: string;
  offset_qb_account_id?: string;
  offset_qb_account_name?: string;
}

export interface AuditEntry {
  id: string;
  action: string;
  actor_id: string;
  comment?: string;
  before_state?: Record<string, unknown>;
  after_state?: Record<string, unknown>;
  created_at: string;
}

export async function getReconciliationSetup(): Promise<ReconciliationSetup> {
  return apiFetch("/reconciliation/setup");
}

export async function previewReconciliationBalances(params: {
  monoAccountId: string;
  qbBankAccountId: string;
  periodEnd: string;
}): Promise<BalancePreview> {
  const q = new URLSearchParams({
    mono_account_id: params.monoAccountId,
    qb_bank_account_id: params.qbBankAccountId,
    period_end: params.periodEnd,
  });
  return apiFetch(`/reconciliation/preview-balances?${q}`);
}

export async function createReconciliationRun(body: {
  mono_account_id: string;
  qb_bank_account_id?: string;
  period_start: string;
  period_end: string;
}): Promise<ReconciliationRun> {
  return apiFetch("/reconciliation/runs", { method: "POST", body: JSON.stringify(body) });
}

export async function getReconciliationRun(runId: string): Promise<ReconciliationRun> {
  return apiFetch(`/reconciliation/runs/${runId}`);
}

export async function listReconciliationItems(
  runId: string,
  matchStatus?: string
): Promise<{ items: ReconciliationItem[] }> {
  const q = matchStatus ? `?match_status=${encodeURIComponent(matchStatus)}` : "";
  return apiFetch(`/reconciliation/runs/${runId}/items${q}`);
}

export async function updateReconciliationItem(
  runId: string,
  itemId: string,
  body: { match_status?: string; confirm_suggested?: boolean; reject_suggested?: boolean }
): Promise<{ item: ReconciliationItem }> {
  return apiFetch(`/reconciliation/runs/${runId}/items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function getBalanceProof(runId: string): Promise<{ balance_proof: BalanceProof }> {
  return apiFetch(`/reconciliation/runs/${runId}/balance-proof`);
}

export async function recalculateReconciliationRun(runId: string): Promise<ReconciliationRun> {
  return apiFetch(`/reconciliation/runs/${runId}/recalculate`, { method: "POST" });
}

export async function listReconciliationAdjustments(
  runId: string
): Promise<{ adjustments: ReconciliationAdjustment[] }> {
  return apiFetch(`/reconciliation/runs/${runId}/adjustments`);
}

export async function createReconciliationAdjustment(
  runId: string,
  body: {
    item_id?: string;
    adjustment_type: string;
    affects_side: "BANK" | "BOOK";
    amount: number;
    description?: string;
    offset_qb_account_id?: string;
    offset_qb_account_name?: string;
    journal_entry_required?: boolean;
  }
): Promise<{ adjustment: ReconciliationAdjustment }> {
  return apiFetch(`/reconciliation/runs/${runId}/adjustments`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function postReconciliationJournal(
  runId: string,
  adjustmentId: string
): Promise<{ journal_entry_id: string; posted: boolean }> {
  return apiFetch(`/reconciliation/runs/${runId}/adjustments/${adjustmentId}/post`, {
    method: "POST",
  });
}

export async function transitionReconciliationRun(
  runId: string,
  targetStatus: RunStatus,
  comment?: string
): Promise<{ run: ReconciliationRun }> {
  return apiFetch(`/reconciliation/runs/${runId}/transition`, {
    method: "POST",
    body: JSON.stringify({ target_status: targetStatus, comment }),
  });
}

export async function getReconciliationAudit(runId: string): Promise<{ entries: AuditEntry[] }> {
  return apiFetch(`/reconciliation/runs/${runId}/audit`);
}

export const MATCH_STATUS_LABELS: Record<string, string> = {
  MATCHED_EXACT: "Matched (exact)",
  MATCHED_FUZZY: "Matched (fuzzy)",
  SUGGESTED: "Suggested",
  DEPOSITS_IN_TRANSIT: "Deposit in transit",
  OUTSTANDING_PAYMENT: "Outstanding payment",
  UNRECORDED_BANK_CREDIT: "Unrecorded credit",
  UNRECORDED_BANK_CHARGE: "Unrecorded charge",
  TIMING_DIFFERENCE: "Timing difference",
  UNEXPLAINED: "Unexplained",
  PRIOR_PERIOD_CARRY: "Prior period cleared",
  DUPLICATE_ENTRY: "Duplicate",
  DATA_ENTRY_ERROR: "Data entry error",
  FLAG_FOR_REVIEW: "Flag for review",
};

export const MONO_CLASSIFY_OPTIONS = [
  "DEPOSITS_IN_TRANSIT",
  "UNRECORDED_BANK_CHARGE",
  "UNRECORDED_BANK_CREDIT",
  "TIMING_DIFFERENCE",
  "UNEXPLAINED",
  "FLAG_FOR_REVIEW",
] as const;

export const QBO_CLASSIFY_OPTIONS = [
  "OUTSTANDING_PAYMENT",
  "TIMING_DIFFERENCE",
  "DUPLICATE_ENTRY",
  "DATA_ENTRY_ERROR",
  "FLAG_FOR_REVIEW",
] as const;
