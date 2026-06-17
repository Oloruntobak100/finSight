"use client";

import { useState } from "react";
import { apiFetch } from "@/lib/api";
import {
  buildQuickBooksAuthorizeUrl,
  saveQuickBooksOAuthState,
  type QuickBooksOAuthConfig,
} from "@/lib/quickbooks";
import { Button } from "@/components/ui/button";

interface QuickBooksConnectButtonProps {
  className?: string;
  variant?: "default" | "outline";
}

export function QuickBooksConnectButton({
  className,
  variant = "outline",
}: QuickBooksConnectButtonProps) {
  const [loading, setLoading] = useState(false);

  async function handleConnect() {
    setLoading(true);
    try {
      const config = await apiFetch<QuickBooksOAuthConfig>("/oauth/quickbooks/config");
      if (!config.configured || !config.client_id) {
        throw new Error("QuickBooks is not configured. Add credentials on the server.");
      }

      const state = crypto.randomUUID();
      saveQuickBooksOAuthState(state);
      window.location.href = buildQuickBooksAuthorizeUrl(config, state);
    } catch (err) {
      setLoading(false);
      const message = err instanceof Error ? err.message : "Failed to start QuickBooks connection";
      alert(message);
    }
  }

  return (
    <Button
      type="button"
      onClick={handleConnect}
      loading={loading}
      loadingLabel="Opening QuickBooks…"
      variant={variant}
      className={className ?? "w-full"}
    >
      Connect QuickBooks
    </Button>
  );
}
