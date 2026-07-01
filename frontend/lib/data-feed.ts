import { apiFetch, DATA_FEED_TIMEOUT_MS } from "@/lib/api";

export type PersonaType = "individual" | "freelancer" | "small_business" | "retail";

export interface SyntheticFeedProfile {
  id: string;
  account_id: string;
  persona_type: PersonaType;
  persona_config: Record<string, unknown>;
  historical_start?: string | null;
  historical_end?: string | null;
  live_feed_enabled: boolean;
  live_interval_hours: number;
  daily_tx_min: number;
  daily_tx_max: number;
  daily_tx_target: number;
  auto_classify: boolean;
  status: string;
  last_backfill_at?: string | null;
  next_live_run_at?: string | null;
  last_live_run_at?: string | null;
}

export interface SyntheticFeedAccount {
  id: string;
  account_name: string;
  provider: string;
  status: string;
  last_synced_at: string | null;
  profile?: SyntheticFeedProfile | null;
  live_feed_enabled?: boolean;
  next_live_run_at?: string | null;
  last_live_run_at?: string | null;
  last_live_drip?: {
    status: string;
    error?: string | null;
    transactions_created?: number;
    started_at?: string;
  } | null;
}

export interface SyntheticFeedStatus {
  enabled: boolean;
  accounts: SyntheticFeedAccount[];
}

export interface SyntheticFeedRun {
  id: string;
  run_type: string;
  transactions_created: number;
  status: string;
  error?: string | null;
  started_at: string;
  finished_at?: string | null;
}

export interface AccountDetail {
  profile: SyntheticFeedProfile;
  runs: SyntheticFeedRun[];
  presets: Record<string, Record<string, unknown>>;
  stats?: { total: number; synthetic: number; mono_imported: number; non_synthetic: number };
}

export interface ArchiveResult {
  archived: number;
  remaining_total: number;
  remaining_synthetic: number;
}

export interface GenerateResult {
  created: number;
  classified: number;
  classify_pending?: boolean;
  run_id: string;
  next_live_run_at?: string;
}

export function fetchFeedStatus() {
  return apiFetch<SyntheticFeedStatus>("/synthetic-feed/status");
}

export function fetchAccountDetail(accountId: string) {
  return apiFetch<AccountDetail>(`/synthetic-feed/accounts/${accountId}`);
}

export function saveProfile(accountId: string, body: Record<string, unknown>) {
  return apiFetch<{ profile: SyntheticFeedProfile }>(`/synthetic-feed/accounts/${accountId}/profile`, {
    method: "PUT",
    body: JSON.stringify(body),
    timeoutMs: DATA_FEED_TIMEOUT_MS,
  });
}

export function importMonoHistory(accountId: string, start: string, end: string) {
  return apiFetch<{ imported: number; start: string; end: string; run_id: string }>(
    `/synthetic-feed/accounts/${accountId}/import-mono`,
    { method: "POST", body: JSON.stringify({ start, end }), timeoutMs: DATA_FEED_TIMEOUT_MS }
  );
}

export function fillHistory(accountId: string, start: string, end: string, count?: number) {
  return apiFetch<GenerateResult>(
    `/synthetic-feed/accounts/${accountId}/fill-history`,
    { method: "POST", body: JSON.stringify({ start, end, count }), timeoutMs: DATA_FEED_TIMEOUT_MS }
  );
}

export function startLiveFeed(accountId: string) {
  return apiFetch<{
    profile: SyntheticFeedProfile;
    interval_hours?: number;
    first_drip?: GenerateResult;
    first_drip_error?: string;
  }>(`/synthetic-feed/accounts/${accountId}/live-feed/start`, {
    method: "POST",
    timeoutMs: DATA_FEED_TIMEOUT_MS,
  });
}

export function pauseLiveFeed(accountId: string) {
  return apiFetch<{ profile: SyntheticFeedProfile }>(
    `/synthetic-feed/accounts/${accountId}/live-feed/pause`,
    { method: "POST" }
  );
}

export function runLiveDripNow(accountId: string) {
  return apiFetch<GenerateResult>(
    `/synthetic-feed/accounts/${accountId}/live-feed/run-now`,
    { method: "POST", timeoutMs: DATA_FEED_TIMEOUT_MS }
  );
}

export function purgeMonoDummies(accountId: string) {
  return apiFetch<ArchiveResult>(
    `/synthetic-feed/accounts/${accountId}/purge-mono-dummies`,
    { method: "POST", timeoutMs: DATA_FEED_TIMEOUT_MS }
  );
}

export function keepSyntheticOnly(accountId: string) {
  return apiFetch<ArchiveResult>(
    `/synthetic-feed/accounts/${accountId}/keep-synthetic-only`,
    { method: "POST", timeoutMs: DATA_FEED_TIMEOUT_MS }
  );
}

export function resetSynthetic(accountId: string) {
  return apiFetch<ArchiveResult>(
    `/synthetic-feed/accounts/${accountId}/reset-synthetic`,
    { method: "POST", timeoutMs: DATA_FEED_TIMEOUT_MS }
  );
}

/** Remove all non-synthetic rows across every connected account (Mono dummy cleanup). */
export function cleanupKeepSyntheticOnlyUser() {
  return apiFetch<ArchiveResult>("/transactions/cleanup/keep-synthetic-only", {
    method: "POST",
    timeoutMs: DATA_FEED_TIMEOUT_MS,
  });
}

export function datePresetMonths(months: number): { start: string; end: string } {
  const end = new Date();
  const start = new Date();
  start.setMonth(start.getMonth() - months);
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  };
}

/** First and last day of a calendar month (defaults to current month). */
export function datePresetCalendarMonth(year?: number, month?: number): { start: string; end: string } {
  const now = new Date();
  const y = year ?? now.getFullYear();
  const m = month ?? now.getMonth();
  const start = new Date(y, m, 1);
  const end = new Date(y, m + 1, 0);
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  };
}

/** January (or first month) of a calendar year — good default for a clean yearly restart. */
export function datePresetFirstMonthOfYear(year?: number): { start: string; end: string } {
  const y = year ?? new Date().getFullYear();
  return datePresetCalendarMonth(y, 0);
}

export const PERSONA_LABELS: Record<PersonaType, string> = {
  individual: "Individual",
  freelancer: "Freelancer",
  small_business: "Small business",
  retail: "Retail shop",
};

export function formatLiveFeedSchedule(profile: Pick<SyntheticFeedProfile, "live_interval_hours">) {
  const hours = profile.live_interval_hours || 6;
  return `every ${hours}h`;
}

export function formatLiveFeedTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function formatDailyTxRange(profile: Pick<SyntheticFeedProfile, "daily_tx_min" | "daily_tx_max" | "daily_tx_target">) {
  const lo = profile.daily_tx_min ?? Math.max(1, profile.daily_tx_target - 7);
  const hi = profile.daily_tx_max ?? Math.min(500, profile.daily_tx_target + 7);
  return `${lo}–${hi}/day`;
}
