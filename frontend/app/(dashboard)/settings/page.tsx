import { createClient } from "@/lib/supabase/server";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";

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
        <p className="text-slate-400">Manage your account and preferences</p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
        </CardHeader>
        <dl className="space-y-3 text-sm">
          <div className="flex justify-between">
            <dt className="text-slate-400">Email</dt>
            <dd className="text-white">{user?.email}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-400">Name</dt>
            <dd className="text-white">{profile?.full_name || "—"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-400">Country</dt>
            <dd className="text-white">{profile?.country || "—"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-400">Currency</dt>
            <dd className="text-white">{profile?.currency || "USD"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-400">Plan</dt>
            <dd className="text-white capitalize">{profile?.plan_tier || "free"}</dd>
          </div>
        </dl>
      </Card>
    </div>
  );
}
