const CATEGORY_LABELS: Record<string, string> = {
  INCOME: "Income",
  TRANSFER_IN: "Transfer In",
  TRANSFER_OUT: "Transfer Out",
  LOAN_PAYMENTS: "Loan Payments",
  BANK_FEES: "Bank Fees",
  ENTERTAINMENT: "Entertainment",
  FOOD_AND_DRINK: "Food & Drink",
  GENERAL_MERCHANDISE: "General Merchandise",
  HOME_IMPROVEMENT: "Home Improvement",
  MEDICAL: "Medical",
  PERSONAL_CARE: "Personal Care",
  GENERAL_SERVICES: "General Services",
  GOVERNMENT_AND_NON_PROFIT: "Government & Non-profit",
  TRANSPORTATION: "Transportation",
  TRAVEL: "Travel",
  RENT_AND_UTILITIES: "Rent & Utilities",
  UNCATEGORIZED: "Uncategorized",
  TRANSFER: "Transfer",
};

export interface TransactionDetails {
  flow?: "incoming" | "outgoing" | null;
  flow_label?: string | null;
  counterparty?: string | null;
  counterparty_bank?: string | null;
  channel?: string | null;
  payment_method?: string | null;
  payment_processor?: string | null;
  reference?: string | null;
  location?: string | null;
  reason?: string | null;
  narration?: string | null;
  summary?: string | null;
}

function titleCase(value: string): string {
  return value
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatCategoryLabel(category: string | null | undefined): string {
  if (!category) return "Uncategorized";
  const key = category.trim().toUpperCase();
  if (CATEGORY_LABELS[key]) return CATEGORY_LABELS[key];
  if (category.includes("_")) return titleCase(category);
  return category;
}

interface MonoNarrationParts {
  payee: string;
  bank?: string;
  channel?: string;
  action?: string;
}

function parseMonoNarrationParts(narration: string): MonoNarrationParts | null {
  const parts = narration.split("/").map((p) => p.trim()).filter(Boolean);
  if (parts.length >= 3 && parts[0].toUpperCase() === "NIP") {
    const bank = titleCase(parts[1]);
    const payee = titleCase(parts[2]);
    const actionRaw = parts[3] || "Transfer";
    const action = actionRaw.replace(/\s+\d+$/, "").trim() || "Transfer";
    return { payee, bank, channel: "NIP", action: titleCase(action) };
  }

  if (parts.length >= 2 && ["POS", "WEB", "ATM"].includes(parts[0].toUpperCase())) {
    const channel = parts[0].toUpperCase();
    return { payee: titleCase(parts[1]), channel, action: `${channel} payment` };
  }

  return null;
}

function looksLikeMonoNarration(value: string): boolean {
  const upper = value.toUpperCase();
  return (
    upper.startsWith("NIP/") ||
    upper.startsWith("POS/") ||
    upper.startsWith("WEB/") ||
    upper.startsWith("ATM/")
  );
}

function flowPrefix(transactionType: "debit" | "credit"): string {
  return transactionType === "credit" ? "Received from" : "Sent to";
}

export function getTransactionDetails(txn: {
  source_provider?: string;
  transaction_type: "debit" | "credit";
  merchant_name?: string | null;
  description?: string | null;
  details?: TransactionDetails | null;
}): TransactionDetails {
  if (txn.details) return txn.details;

  const flow = txn.transaction_type === "credit" ? "incoming" : "outgoing";
  const flowLabel = txn.transaction_type === "credit" ? "From" : "To";
  const merchant = txn.merchant_name?.trim() || "";
  const description = txn.description?.trim() || "";
  const raw = merchant || description;

  const details: TransactionDetails = {
    flow,
    flow_label: flowLabel,
    counterparty: merchant || null,
    summary: description || null,
  };

  if (raw && (txn.source_provider === "mono" || looksLikeMonoNarration(raw))) {
    details.narration = raw.includes("/") ? raw : null;
    const parsed = raw.includes("/") ? parseMonoNarrationParts(raw) : null;
    if (parsed) {
      details.counterparty = parsed.payee;
      details.counterparty_bank = parsed.bank ?? null;
      details.channel = parsed.channel ?? null;
      const summaryParts = [flowPrefix(txn.transaction_type), parsed.payee];
      if (parsed.bank) summaryParts.push(`via ${parsed.bank}`);
      if (parsed.channel) summaryParts.push(`(${parsed.channel})`);
      details.summary = summaryParts.join(" ");
    }
  }

  if (details.counterparty && !details.summary) {
    details.summary = `${flowPrefix(txn.transaction_type)} ${details.counterparty}`;
  }

  return details;
}

function inferCategory(txn: {
  category?: string | null;
  merchant_name?: string | null;
  description?: string | null;
  source_provider?: string;
  transaction_type?: "debit" | "credit";
}): string | null {
  const existing = txn.category?.trim();
  if (existing && existing.toLowerCase() !== "uncategorized") {
    return existing;
  }

  const text = [txn.merchant_name, txn.description].filter(Boolean).join(" ");
  if (!text) return existing || null;

  const lower = text.toLowerCase();
  if (
    txn.source_provider === "mono" ||
    looksLikeMonoNarration(text) ||
    /\b(nip|transfer|trf)\b/.test(lower)
  ) {
    return txn.transaction_type === "credit" ? "Transfer In" : "Transfer Out";
  }

  return existing || null;
}

export function getCategoryDisplay(txn: {
  category?: string | null;
  sub_category?: string | null;
  merchant_name?: string | null;
  description?: string | null;
  source_provider?: string;
  transaction_type?: "debit" | "credit";
}): { primary: string; secondary: string | null } {
  const primary = formatCategoryLabel(inferCategory(txn) ?? txn.category);
  const subRaw = txn.sub_category?.trim();
  if (!subRaw) return { primary, secondary: null };

  const secondary = formatCategoryLabel(subRaw);
  if (secondary.toLowerCase() === primary.toLowerCase()) {
    return { primary, secondary: null };
  }
  return { primary, secondary };
}

export function truncateText(value: string | null | undefined, max = 48): string {
  if (!value) return "—";
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1)}…`;
}
