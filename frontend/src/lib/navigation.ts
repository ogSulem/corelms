/**
 * Пункты основной навигации — один источник правды для шапки и нижней панели.
 *
 * `short` — подпись на телефоне. В нижней панели на iPhone пять ячеек по ~78 px,
 * поэтому подпись обязана быть короткой: «Админ‑центр» туда не влезает и
 * обрезается, а раньше он вообще уезжал за правый край экрана.
 */
export type NavRole = string | undefined;

export type NavSpec = {
  href: string;
  label: string;
  short: string;
  icon: "dashboard" | "learning" | "sales" | "account" | "admin";
};

/** Максимум символов для подписи в нижней панели (10 px, ячейка ~78 px). */
export const MOBILE_LABEL_MAX = 8;

export const NAV_ITEMS: NavSpec[] = [
  { href: "/dashboard", label: "Дашборд", short: "Главная", icon: "dashboard" },
  { href: "/modules", label: "Обучение", short: "Обучение", icon: "learning" },
  { href: "/sales", label: "Продажи", short: "Продажи", icon: "sales" },
  { href: "/account", label: "Кабинет", short: "Кабинет", icon: "account" },
];

export const ADMIN_NAV_ITEM: NavSpec = { href: "/admin/modules", label: "Админ‑центр", short: "Админка", icon: "admin" };

export function navItemsFor(role: NavRole): NavSpec[] {
  const isAdmin = role === "admin" || role === "superadmin";
  return isAdmin ? [...NAV_ITEMS, ADMIN_NAV_ITEM] : [...NAV_ITEMS];
}

export function isNavItemActive(pathname: string, href: string): boolean {
  if (href === ADMIN_NAV_ITEM.href) return pathname.startsWith("/admin/") || pathname === "/admin";
  return pathname === href || pathname.startsWith(`${href}/`);
}
