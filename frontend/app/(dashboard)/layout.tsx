import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { Sidebar } from "@/components/dashboard/sidebar";
import { DashboardHeader } from "@/components/dashboard/header";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const user = session?.user;

  if (!user) redirect("/login");

  const { data: profile } = await supabase
    .from("users")
    .select("plan_tier, onboarded_at")
    .eq("id", user.id)
    .single();

  if (!profile?.onboarded_at && !user.email?.includes("skip")) {
    // Allow dashboard access; onboarding optional for dev
  }

  return (
    <div className="flex min-h-screen overflow-x-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <DashboardHeader email={user.email} plan={profile?.plan_tier || "free"} />
        <main className="min-w-0 flex-1 overflow-x-hidden overflow-y-auto p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
