"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const TABS = [
  { href: "/books", label: "Queue", exact: true },
  { href: "/books/mappings", label: "Mappings", exact: false },
] as const;

export function BooksNav() {
  const pathname = usePathname();

  return (
    <nav className="flex gap-1 overflow-x-auto rounded-lg border border-slate-800/60 bg-slate-950/40 p-1">
      {TABS.map((tab) => {
        const active = tab.exact ? pathname === tab.href : pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={cn(
              "shrink-0 rounded-md px-4 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-blue-600 text-white shadow-sm"
                : "text-slate-400 hover:bg-slate-800/80 hover:text-white"
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
