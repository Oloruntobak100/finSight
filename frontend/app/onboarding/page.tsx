"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const USE_CASES = ["Personal Finance", "Freelancer", "Small Business"];
const GOALS = ["Save money", "Reduce expenses", "Track spending", "Grow revenue"];

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [fullName, setFullName] = useState("");
  const [country, setCountry] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [useCase, setUseCase] = useState("");
  const [goal, setGoal] = useState("");

  async function complete() {
    const supabase = createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) return;

    await supabase
      .from("users")
      .update({
        full_name: fullName,
        country,
        currency,
        onboarded_at: new Date().toISOString(),
      })
      .eq("id", user.id);

    router.push("/accounts");
    router.refresh();
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle>Welcome to FinSight AI</CardTitle>
          <CardDescription>Step {step} of 4</CardDescription>
        </CardHeader>

        {step === 1 && (
          <div className="space-y-4">
            <Input placeholder="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
            <Input placeholder="Country" value={country} onChange={(e) => setCountry(e.target.value)} />
            <Input placeholder="Currency (e.g. USD, NGN)" value={currency} onChange={(e) => setCurrency(e.target.value)} />
            <Button className="w-full" onClick={() => setStep(2)}>
              Continue
            </Button>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-3">
            {USE_CASES.map((uc) => (
              <button
                key={uc}
                onClick={() => setUseCase(uc)}
                className={`w-full rounded-lg border px-4 py-3 text-left ${
                  useCase === uc ? "border-blue-500 bg-blue-500/10" : "border-slate-700"
                }`}
              >
                {uc}
              </button>
            ))}
            <Button className="w-full" onClick={() => setStep(3)} disabled={!useCase}>
              Continue
            </Button>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <p className="text-sm text-slate-400">Connect your first account on the next screen.</p>
            <Button className="w-full" onClick={() => setStep(4)}>
              Continue
            </Button>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-3">
            {GOALS.map((g) => (
              <button
                key={g}
                onClick={() => setGoal(g)}
                className={`w-full rounded-lg border px-4 py-3 text-left ${
                  goal === g ? "border-blue-500 bg-blue-500/10" : "border-slate-700"
                }`}
              >
                {g}
              </button>
            ))}
            <Button className="w-full" onClick={complete} disabled={!goal}>
              Get Started
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
