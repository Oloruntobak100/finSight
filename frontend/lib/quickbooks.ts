const QB_STATE_KEY = "quickbooks_oauth_state";
const QB_STATE_TS_KEY = "quickbooks_oauth_state_timestamp";
const STATE_MAX_AGE_MS = 15 * 60 * 1000;

export interface QuickBooksOAuthConfig {
  client_id: string;
  redirect_uri: string;
  scope: string;
  oauth_url: string;
  environment: string;
  configured: boolean;
}

export function saveQuickBooksOAuthState(state: string) {
  sessionStorage.setItem(QB_STATE_KEY, state);
  sessionStorage.setItem(QB_STATE_TS_KEY, String(Date.now()));
}

export function consumeQuickBooksOAuthState(incoming: string | null): void {
  const saved = sessionStorage.getItem(QB_STATE_KEY);
  const savedAt = Number(sessionStorage.getItem(QB_STATE_TS_KEY) || "0");

  sessionStorage.removeItem(QB_STATE_KEY);
  sessionStorage.removeItem(QB_STATE_TS_KEY);

  if (!incoming) throw new Error("Missing security verification");
  if (!saved) throw new Error("Security verification failed — please try connecting again");
  if (incoming !== saved) throw new Error("Security verification mismatch");
  if (Date.now() - savedAt > STATE_MAX_AGE_MS) {
    throw new Error("Connection session expired — please try again");
  }
}

export function buildQuickBooksAuthorizeUrl(config: QuickBooksOAuthConfig, state: string): string {
  const url = new URL(config.oauth_url);
  url.searchParams.set("client_id", config.client_id);
  url.searchParams.set("redirect_uri", config.redirect_uri);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", config.scope);
  url.searchParams.set("state", state);
  return url.toString();
}

export function clearQuickBooksOAuthState() {
  sessionStorage.removeItem(QB_STATE_KEY);
  sessionStorage.removeItem(QB_STATE_TS_KEY);
}
