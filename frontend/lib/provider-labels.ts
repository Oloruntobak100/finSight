/** User-facing labels — hide underlying bank aggregation providers (Plaid, Mono). */

export function providerDisplayName(provider: string | undefined | null): string {
  switch (provider) {
    case "plaid":
    case "mono":
      return "Bank";
    case "quickbooks":
      return "QuickBooks";
    case "xero":
      return "Xero";
    default:
      return provider ? provider.charAt(0).toUpperCase() + provider.slice(1) : "Account";
  }
}

export function bankConnectCardTitle(provider: "plaid" | "mono"): string {
  return provider === "plaid" ? "US & UK Banks" : "Africa Banks";
}

export function bankConnectCardDescription(provider: "plaid" | "mono", sandbox?: boolean): string {
  const region = provider === "plaid" ? "United States & United Kingdom" : "Nigeria & Africa";
  return sandbox ? `${region} · Sandbox` : region;
}

export function bankSourceFilterLabel(provider: "plaid" | "mono"): string {
  return provider === "plaid" ? "US & UK banks" : "Africa banks";
}
