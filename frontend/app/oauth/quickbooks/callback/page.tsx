"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { clearQuickBooksOAuthState, consumeQuickBooksOAuthState } from "@/lib/quickbooks";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Stage = "validating" | "exchanging" | "success" | "error";

function QuickBooksCallbackContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [stage, setStage] = useState<Stage>("validating");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    void processCallback();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function processCallback() {
    try {
      const error = searchParams.get("error");
      const errorDescription = searchParams.get("error_description");
      if (error) {
        setStage("error");
        setErrorMessage(
          errorDescription ||
            (error === "access_denied" ? "You cancelled the QuickBooks authorization" : "Authorization failed")
        );
        return;
      }

      const code = searchParams.get("code");
      const realmId = searchParams.get("realmId");
      const state = searchParams.get("state");

      setStage("validating");
      consumeQuickBooksOAuthState(state);

      if (!code || !realmId) {
        throw new Error("Missing authorization data from QuickBooks");
      }

      setStage("exchanging");
      await apiFetch("/oauth/quickbooks/exchange", {
        method: "POST",
        body: JSON.stringify({ code, realmId }),
      });

      setStage("success");
      router.replace("/accounts?connected=quickbooks");
      router.refresh();
    } catch (err) {
      clearQuickBooksOAuthState();
      setStage("error");
      setErrorMessage(err instanceof Error ? err.message : "An unexpected error occurred");
    }
  }

  if (stage === "error") {
    return (
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="mb-2 flex justify-center">
            <XCircle className="h-10 w-10 text-red-400" />
          </div>
          <CardTitle className="text-center">QuickBooks connection failed</CardTitle>
          <CardDescription className="text-center text-red-300">{errorMessage}</CardDescription>
        </CardHeader>
        <div className="flex flex-col gap-2 px-6 pb-6">
          <Button asChild>
            <Link href="/accounts">Back to accounts</Link>
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <div className="mb-2 flex justify-center">
          {stage === "success" ? (
            <CheckCircle2 className="h-10 w-10 text-green-400" />
          ) : (
            <Loader2 className="h-10 w-10 animate-spin text-blue-400" />
          )}
        </div>
        <CardTitle className="text-center">Connecting QuickBooks</CardTitle>
        <CardDescription className="text-center">
          {stage === "validating" && "Verifying your authorization…"}
          {stage === "exchanging" && "Securing your connection…"}
          {stage === "success" && "Connected! Redirecting…"}
        </CardDescription>
      </CardHeader>
    </Card>
  );
}

export default function QuickBooksCallbackPage() {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Suspense fallback={<div className="text-slate-400">Loading…</div>}>
        <QuickBooksCallbackContent />
      </Suspense>
    </div>
  );
}
