"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/cn";

const baseItems = [
  { href: "/dashboard", label: "Дашборд" },
  { href: "/modules", label: "Обучение" },
  { href: "/account", label: "Кабинет" },
];

export function AppNav({ role, authenticated = true }: { role?: string; authenticated?: boolean }) {
  const pathname = usePathname();

  const items = role === "admin" ? [...baseItems, { href: "/adminpanel", label: "Админ‑центр" }] : baseItems;

  return (
    <nav className="flex items-center gap-1 rounded-2xl border border-zinc-200 bg-white/85 backdrop-blur-xl p-1.5 shadow-sm shadow-zinc-950/5">
      {items.map((it) => {
        const active = pathname === it.href || pathname.startsWith(it.href + "/");
        return (
          <Link
            key={it.href}
            href={it.href}
            className={cn(
              "relative rounded-xl px-3.5 py-2.5 text-sm transition font-black uppercase tracking-widest text-[10px]",
              active
                ? "bg-[#fe9900]/15 text-zinc-950 shadow-sm border border-[#fe9900]/25"
                : "text-zinc-700 hover:text-zinc-950 hover:bg-zinc-50"
            )}
          >
            {it.label}
          </Link>
        );
      })}
    </nav>
  );
}
