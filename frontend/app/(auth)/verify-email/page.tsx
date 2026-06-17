"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { OtpInput } from "@/components/auth/otp-input";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function VerifyEmailForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const email = searchParams.get("email") ?? "";

  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);

  async function handleVerify(e: React.FormEvent) {
    e.preventDefault();
    if (!email) {
      setError("Missing email. Please register again.");
      return;
    }
    if (code.length !== 6) {
      setError("Enter the 6-digit code from your email.");
      return;
    }

    setLoading(true);
    setError("");
    const supabase = createClient();
    const { error: verifyError } = await supabase.auth.verifyOtp({
      email,
      token: code,
      type: "signup",
    });
    setLoading(false);

    if (verifyError) {
      setError(verifyError.message);
      return;
    }

    router.push("/");
    router.refresh();
  }

  async function handleResend() {
    if (!email) return;
    setResending(true);
    setError("");
    setResent(false);
    const supabase = createClient();
    const { error: resendError } = await supabase.auth.resend({
      type: "signup",
      email,
    });
    setResending(false);
    if (resendError) {
      setError(resendError.message);
      return;
    }
    setResent(true);
  }

  if (!email) {
    return (
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Verification unavailable</CardTitle>
          <CardDescription>We could not find your email address.</CardDescription>
        </CardHeader>
        <p className="px-6 pb-6 text-center text-sm text-slate-400">
          <Link href="/register" className="text-blue-400 hover:underline">
            Go back to register
          </Link>
        </p>
      </Card>
    );
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Verify your email</CardTitle>
        <CardDescription>
          Enter the 6-digit code we sent to <span className="text-slate-200">{email}</span>
        </CardDescription>
      </CardHeader>
      <form onSubmit={handleVerify} className="space-y-6 px-6 pb-6">
        <OtpInput value={code} onChange={setCode} disabled={loading} />
        {error && <p className="text-center text-sm text-red-400">{error}</p>}
        {resent && <p className="text-center text-sm text-emerald-400">A new code has been sent.</p>}
        <Button type="submit" className="w-full" disabled={loading || code.length !== 6}>
          {loading ? "Verifying..." : "Verify and continue"}
        </Button>
        <p className="text-center text-sm text-slate-400">
          Didn&apos;t get a code?{" "}
          <button
            type="button"
            onClick={handleResend}
            disabled={resending}
            className="text-blue-400 hover:underline disabled:opacity-50"
          >
            {resending ? "Sending..." : "Resend code"}
          </button>
        </p>
      </form>
    </Card>
  );
}

export default function VerifyEmailPage() {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Suspense fallback={<div className="text-slate-400">Loading...</div>}>
        <VerifyEmailForm />
      </Suspense>
    </div>
  );
}
