"use client";

import Link from "next/link";
import { useLinkStatus } from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  MessageSquare,
  Link2,
  TrendingUp,
  Repeat,
  FileText,
  Settings,
  Sparkles,
  Receipt,
  BarChart3,
  BookOpen,
  FlaskConical,
} from "lucide-react";
import { NavProgress } from "@/components/dashboard/nav-progress";
import { LoaderIcon } from "@/components/ui/page-loader";
import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string; icon: React.ComponentType<{ className?: string }> };

const MAIN_NAV: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/transactions", label: "Transactions", icon: Receipt },
  { href: "/books", label: "Books", icon: BookOpen },
  { href: "/reconciliation", label: "Bank check", icon: FileText },
];

const ANALYTICS_NAV: NavItem[] = [
  { href: "/analysis", label: "Analysis", icon: BarChart3 },
  { href: "/forecast", label: "Forecast", icon: TrendingUp },
  { href: "/reports", label: "Reports", icon: FileText },
];

const MORE_NAV: NavItem[] = [
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/accounts", label: "Accounts", icon: Link2 },
  { href: "/data-feed", label: "Data Feed", icon: FlaskConical },
  { href: "/subscriptions", label: "Subscriptions", icon: Repeat },
  { href: "/settings", label: "Settings", icon: Settings },
];

function NavItemInner({
  label,
  icon: Icon,
  highlighted,
}: {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  highlighted: boolean;
}) {
  const { pending } = useLinkStatus();

  return (
    <span
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all duration-150",
        highlighted || pending
          ? "bg-blue-600/20 text-blue-400 shadow-[inset_0_0_0_1px_rgba(59,130,246,0.25)]"
          : "text-slate-400 hover:bg-slate-800 hover:text-white",
        pending && "scale-[0.99]"
      )}
    >
      <Icon className={cn("h-4 w-4 shrink-0", pending && "text-blue-400")} />
      <span className="flex-1">{label}</span>
      {pending && <LoaderIcon />}
    </span>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const [pendingHref, setPendingHref] = useState<string | null>(null);

  useEffect(() => {
    setPendingHref(null);
  }, [pathname]);

  const isNavigating = pendingHref !== null && pendingHref !== pathname;

  function renderNav(items: NavItem[]) {
    return items.map((item) => {
      const isActive = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
      const isPending = pendingHref === item.href;
      const highlighted = isActive || isPending;

      return (
        <Link
          key={item.href}
          href={item.href}
          prefetch
          onClick={() => setPendingHref(item.href)}
          className="block rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-blue-500 active:scale-[0.98] transition-transform"
        >
          <NavItemInner label={item.label} icon={item.icon} highlighted={highlighted} />
        </Link>
      );
    });
  }

  return (
    <>
      {isNavigating && <NavProgress />}
      <aside className="hidden md:flex w-64 flex-col border-r border-slate-800 bg-slate-950 p-4">
        <div className="mb-8 flex items-center gap-2 px-2">
          <Sparkles className="h-6 w-6 text-blue-500" />
          <div>
            <p className="font-bold text-white">FinSight AI</p>
            <p className="text-xs text-slate-500">Chat with your finances</p>
          </div>
        </div>
        <nav className="flex-1 space-y-6">
          <div className="space-y-1">{renderNav(MAIN_NAV)}</div>
          <div>
            <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-wider text-slate-600">
              Analytics
            </p>
            <div className="space-y-1">{renderNav(ANALYTICS_NAV)}</div>
          </div>
          <div className="space-y-1">{renderNav(MORE_NAV)}</div>
        </nav>
      </aside>
    </>
  );
}
