"use client";

import { createClient } from "@/lib/supabase/client";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export function DashboardHeader({ email, plan = "free" }: { email?: string; plan?: string }) {
  const router = useRouter();

  async function signOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <header className="flex h-16 items-center justify-between border-b border-slate-800 px-6">
      <div />
      <div className="flex min-w-0 items-center gap-2 md:gap-3">
        <Badge className="capitalize">{plan}</Badge>
        <span className="hidden max-w-[160px] truncate text-sm text-slate-400 lg:inline">{email}</span>
        <Button variant="outline" size="sm" onClick={signOut}>
          Sign out
        </Button>
      </div>
    </header>
  );
}
