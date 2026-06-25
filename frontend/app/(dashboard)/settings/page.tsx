import { createClient } from "@/lib/supabase/server";
import { SettingsAutomation } from "@/components/settings/settings-automation";

export default async function SettingsPage() {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const user = session?.user;
  const { data: profile } = await supabase.from("users").select("*").eq("id", user!.id).single();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-slate-400">Manage your account, AI automation, and learning progress</p>
      </div>
      <SettingsAutomation
        email={user?.email ?? ""}
        fullName={profile?.full_name}
        country={profile?.country}
        currency={profile?.currency}
        plan={profile?.plan_tier}
      />
    </div>
  );
}
