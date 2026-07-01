import { bankSourceFilterLabel } from "@/lib/provider-labels";

export type ComparePeriod = "previous_month" | "previous_year" | "previous_period";
export type ProviderFilter = "" | "plaid" | "mono";
export type DatePreset = "30d" | "90d" | "6m" | "ytd" | "custom";

export interface AnalysisFilterState {
  dateFrom: string;
  dateTo: string;
  provider: ProviderFilter;
  accountIds: string[];
  includeTransfers: boolean;
  comparePeriod: ComparePeriod;
  compareAccountA: string;
  compareAccountB: string;
}

export interface AnalyticsMetaAccount {
  id: string;
  account_name: string;
  provider: string;
  currency: string;
}

export const ANALYSIS_FILTERS_STORAGE_KEY = "finsight-analysis-filters";

export function getDefaultAnalysisFilters(): AnalysisFilterState {
  const today = new Date();
  const sixMonthsAgo = new Date(today);
  sixMonthsAgo.setMonth(sixMonthsAgo.getMonth() - 6);
  return {
    dateFrom: sixMonthsAgo.toISOString().slice(0, 10),
    dateTo: today.toISOString().slice(0, 10),
    provider: "",
    accountIds: [],
    includeTransfers: false,
    comparePeriod: "previous_month",
    compareAccountA: "",
    compareAccountB: "",
  };
}

export function loadAnalysisFilters(): AnalysisFilterState {
  const defaults = getDefaultAnalysisFilters();
  if (typeof window === "undefined") return defaults;
  try {
    const raw = localStorage.getItem(ANALYSIS_FILTERS_STORAGE_KEY);
    if (!raw) return defaults;
    return { ...defaults, ...JSON.parse(raw) };
  } catch {
    return defaults;
  }
}

export function saveAnalysisFilters(filters: AnalysisFilterState) {
  if (typeof window === "undefined") return;
  localStorage.setItem(ANALYSIS_FILTERS_STORAGE_KEY, JSON.stringify(filters));
}

export function buildAnalysisQueryString(filters: AnalysisFilterState): string {
  const params = new URLSearchParams();
  if (filters.dateFrom) params.set("date_from", filters.dateFrom);
  if (filters.dateTo) params.set("date_to", filters.dateTo);
  if (filters.provider) params.append("provider", filters.provider);
  filters.accountIds.forEach((id) => params.append("account_id", id));
  if (filters.includeTransfers) params.set("include_transfers", "true");
  if (filters.comparePeriod) params.set("compare_period", filters.comparePeriod);
  if (filters.compareAccountA) params.set("compare_account_a", filters.compareAccountA);
  if (filters.compareAccountB) params.set("compare_account_b", filters.compareAccountB);
  return params.toString();
}

export function applyDatePreset(preset: DatePreset): Pick<AnalysisFilterState, "dateFrom" | "dateTo"> {
  const today = new Date();
  const to = today.toISOString().slice(0, 10);
  const from = new Date(today);
  if (preset === "30d") from.setDate(from.getDate() - 30);
  else if (preset === "90d") from.setDate(from.getDate() - 90);
  else if (preset === "6m") from.setMonth(from.getMonth() - 6);
  else if (preset === "ytd") from.setMonth(0, 1);
  return { dateFrom: from.toISOString().slice(0, 10), dateTo: to };
}

export function filterSummaryChips(
  filters: AnalysisFilterState,
  accounts: AnalyticsMetaAccount[]
): string[] {
  const chips: string[] = [];
  if (filters.dateFrom && filters.dateTo) {
    chips.push(`${filters.dateFrom} → ${filters.dateTo}`);
  }
  if (filters.provider) {
    chips.push(bankSourceFilterLabel(filters.provider));
  }
  if (filters.accountIds.length > 0) {
    const names = filters.accountIds
      .map((id) => accounts.find((a) => a.id === id)?.account_name || id)
      .join(", ");
    chips.push(names);
  } else {
    chips.push("All accounts");
  }
  chips.push(filters.includeTransfers ? "incl. transfers" : "excl. transfers");
  const periodLabels: Record<ComparePeriod, string> = {
    previous_month: "vs last month",
    previous_year: "vs last year",
    previous_period: "vs prior period",
  };
  chips.push(periodLabels[filters.comparePeriod]);
  return chips;
}
