"use client";

import { usePathname } from "next/navigation";
import { Suspense, type ReactNode } from "react";
import dynamic from "next/dynamic";
const AdminPanelClient = dynamic(() => import("../adminpanel/adminpanel-client"), {
  ssr: false,
  loading: () => <p role="status" className="p-10 text-center text-sm text-zinc-500">Загружаем раздел администрирования…</p>,
});

function AdminRoute({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  // The normal library/editor never mount the legacy polling/analytics screen.
  if (pathname.startsWith("/admin/modules/") || pathname === "/admin/modules" || pathname === "/admin/settings") return <>{children}</>;
  return <><AdminPanelClient />{children}</>;
}

export default function AdminLayout({ children }: { children: ReactNode }) {
  return <Suspense fallback={<div role="status" className="p-10 text-center text-sm text-zinc-500">Загружаем раздел…</div>}><AdminRoute>{children}</AdminRoute></Suspense>;
}
