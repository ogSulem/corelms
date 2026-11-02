"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, LayoutDashboard, ShieldCheck, UserRound, Wallet } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/cn";
import { isNavItemActive, navItemsFor, type NavSpec } from "@/lib/navigation";

const ICONS: Record<NavSpec["icon"], LucideIcon> = {
  dashboard: LayoutDashboard,
  learning: BookOpen,
  sales: Wallet,
  account: UserRound,
  admin: ShieldCheck,
};

/**
 * Навигация в шапке — только на широких экранах.
 *
 * Раньше этот же блок стоял в шапке и на телефоне. Пять пунктов («Дашборд»,
 * «Обучение», «Продажи», «Кабинет», «Админ‑центр») занимают на iPhone около
 * 390 px при доступных 358 — последний пункт уезжал за экран, а про
 * горизонтальную прокрутку ничего не подсказывало. Поэтому на телефоне
 * навигация переехала в нижнюю панель (`AppNavBottom`), где все пункты всегда
 * на виду и под большим пальцем.
 */
export function AppNav({ role, authenticated = true }: { role?: string; authenticated?: boolean }) {
  const pathname = usePathname();
  if (!authenticated) return null;
  const items = navItemsFor(role);

  return (
    <nav aria-label="Основная навигация" className="mx-auto flex w-fit max-w-full min-w-0 items-center gap-1 rounded-2xl border border-zinc-200 bg-white/85 p-1.5 shadow-sm shadow-zinc-950/5 backdrop-blur-xl">
      {items.map((it) => {
        const active = isNavItemActive(pathname, it.href);
        return (
          <Link
            key={it.href}
            href={it.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "relative shrink-0 whitespace-nowrap rounded-xl border border-transparent px-3.5 py-2.5 text-[10px] font-bold uppercase tracking-wider transition",
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

/** Нижняя панель навигации для телефонов и планшетов: ничего не уезжает за экран. */
export function AppNavBottom({ role, authenticated = true }: { role?: string; authenticated?: boolean }) {
  const pathname = usePathname();
  if (!authenticated) return null;
  const items = navItemsFor(role);

  return (
    <nav
      aria-label="Основная навигация"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-zinc-200 bg-white/95 pb-[env(safe-area-inset-bottom)] shadow-[0_-6px_24px_rgba(24,24,27,0.06)] backdrop-blur-xl md:hidden"
    >
      <ul className={cn("mx-auto grid w-full max-w-2xl", items.length === 5 ? "grid-cols-5" : "grid-cols-4")}>
        {items.map((it) => {
          const active = isNavItemActive(pathname, it.href);
          const Icon = ICONS[it.icon];
          return (
            <li key={it.href} className="min-w-0">
              <Link
                href={it.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex min-h-[54px] flex-col items-center justify-center gap-1 px-1 py-1.5 text-[10px] font-semibold leading-none transition-colors active:bg-zinc-100",
                  active ? "text-[#b45309]" : "text-zinc-500 hover:text-zinc-900"
                )}
              >
                <Icon size={20} strokeWidth={active ? 2.4 : 1.9} aria-hidden="true" />
                <span className="w-full truncate text-center">{it.short}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
