"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, LineChart, SlidersHorizontal, Users } from "lucide-react";

// Импорт живёт внутри раздела «Модули» (кнопка «Импорт нового ZIP»),
// а состояние сервера и схемы — в «Настройках»: отдельные пункты меню не нужны.
const items = [
  { href: "/admin/modules", title: "Модули", icon: BookOpen },
  { href: "/admin/users", title: "Пользователи", icon: Users },
  { href: "/admin/analytics", title: "Результаты", icon: LineChart },
  { href: "/admin/settings", title: "Настройки", icon: SlidersHorizontal },
];

export function AdminNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Разделы администрирования" className="mb-8 flex flex-wrap gap-2">
      {items.map(({ href, title, icon: Icon }) => {
        const active = href === "/admin/modules"
          ? pathname.startsWith("/admin/modules") || pathname.startsWith("/admin/import")
          : pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium transition ${
              active
                ? "border-amber-200 bg-amber-50 text-amber-900"
                : "border-zinc-200 bg-white text-zinc-600 hover:border-zinc-300 hover:text-zinc-900"
            }`}
          >
            <Icon size={16} />
            {title}
          </Link>
        );
      })}
    </nav>
  );
}
