import { createClient } from "@/lib/supabase/client";

/** Ensures absolute URL — missing https:// makes fetch hit the Vercel domain as a path. */
export function normalizeApiBase(raw: string | undefined): string {
  const base = (raw || "http://localhost:8000").trim().replace(/\/$/, "");
  if (!base) return "http://localhost:8000";
  if (base.startsWith("http://") || base.startsWith("https://")) return base;
  return `https://${base}`;
}

const API_BASE = normalizeApiBase(process.env.NEXT_PUBLIC_FASTAPI_URL);
const AUTH_TIMEOUT_MS = 8_000;
const FETCH_TIMEOUT_MS = 20_000;
export const BANKING_TIMEOUT_MS = 90_000;
export const BOOKS_CLASSIFY_TIMEOUT_MS = 120_000;
export const BOOKS_APPROVE_TIMEOUT_MS = 90_000;
export const BOOKS_BULK_APPROVE_TIMEOUT_MS = 180_000;
export const DATA_FEED_TIMEOUT_MS = 120_000;
/** Full-period transaction matching can load 1000+ lines + QBO queries. */
export const RECONCILIATION_MATCH_TIMEOUT_MS = 300_000;

export interface ApiFetchOptions extends RequestInit {
  timeoutMs?: number;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getAuthHeaders(): Promise<HeadersInit> {
  const supabase = createClient();
  const sessionPromise = supabase.auth.getSession();
  const timeout = new Promise<never>((_, reject) =>
    setTimeout(() => reject(new ApiError("Auth timed out — try signing in again", 408)), AUTH_TIMEOUT_MS)
  );

  const {
    data: { session },
  } = await Promise.race([sessionPromise, timeout]);

  if (!session?.access_token) {
    throw new ApiError("Not authenticated", 401);
  }
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${session.access_token}`,
  };
}

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { timeoutMs = FETCH_TIMEOUT_MS, ...fetchOptions } = options;
  const headers = await getAuthHeaders();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...fetchOptions,
      headers: { ...headers, ...fetchOptions.headers },
      signal: controller.signal,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const detail = err.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ") || res.statusText
            : typeof detail === "object" && detail !== null && "message" in detail
              ? String((detail as { message?: string }).message)
              : res.statusText || "Request failed";
      throw new ApiError(message, res.status, detail);
    }

    if (res.status === 204) return undefined as T;
    return res.json() as Promise<T>;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(
        `Request timed out — the server at ${API_BASE} took too long to respond`,
        408
      );
    }
    if (err instanceof TypeError && /failed to fetch|networkerror/i.test(err.message)) {
      throw new ApiError(
        `Cannot reach the API at ${API_BASE}. Check that the backend is running, CORS allows this site, and the latest code is deployed.`,
        0
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function apiStream(path: string, body: unknown): Promise<Response> {
  const headers = await getAuthHeaders();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) {
      throw new ApiError("Stream request failed", res.status);
    }
    return res;
  } finally {
    clearTimeout(timer);
  }
}
