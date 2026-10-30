"use client";

import Link from "next/link";
import { useActiveTabVisibility } from "@/lib/hooks/use-active-tab-visibility";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/cn";

const baseItems = [
  { href: "/dashboard", label: "Дашборд" },
  { href: "/modules", label: "Обучение" },
  { href: "/sales", label: "Продажи" },
  { href: "/account", label: "Кабинет" },
];

export function AppNav({ role, authenticated = true }: { role?: string; authenticated?: boolean }) {
  const pathname = usePathname();
  const nav = useActiveTabVisibility(`${pathname}:${role}`);

  const items = role === "admin" || role === "superadmin" ? [...baseItems, { href: "/admin/modules", label: "Админ‑центр" }] : baseItems;

  return (
    <nav ref={nav} aria-label="Основная навигация" className="mx-auto flex w-fit max-w-full min-w-0 items-center gap-1 overflow-x-auto rounded-2xl border border-zinc-200 bg-white/85 p-1.5 shadow-sm shadow-zinc-950/5 backdrop-blur-xl">
      {items.map((it) => {
        const active = it.href === "/admin/modules" ? pathname.startsWith("/admin/") : pathname === it.href || pathname.startsWith(it.href + "/");
        return (
          <Link
            key={it.href}
            href={it.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "relative shrink-0 whitespace-nowrap rounded-xl border border-transparent px-2 py-2.5 text-[10px] font-bold uppercase tracking-wider transition sm:px-3.5",
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
