"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { HelpCircle } from "lucide-react";
import { AppShell } from "@/components/app/shell";
import { AdminNav } from "@/components/admin/admin-nav";
import { ModuleLibrary } from "@/components/admin/module-library";
import { useAuth } from "@/lib/hooks/use-auth";

export default function AdminModulesPage() {
  const params = useSearchParams();
  const router = useRouter();
  const oldModule = params.get("mid"), oldLesson = params.get("sid");
  useEffect(() => {
    if (oldModule) router.replace(`/admin/modules/${encodeURIComponent(oldModule)}?tab=tests${oldLesson ? `&lesson=${encodeURIComponent(oldLesson)}` : ""}`);
  }, [oldModule, oldLesson, router]);
  const { user, loading } = useAuth();
  if (oldModule) return <p role="status" className="p-10 text-center text-sm text-zinc-500">Открываем единый редактор модуля…</p>;
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";
  return <AppShell><div className="mx-auto w-full max-w-7xl px-4 py-8 sm:py-10">
    {loading ? <p role="status" className="py-10 text-center text-sm text-zinc-500">Проверяем доступ…</p> : !isAdmin ? <p role="alert" className="py-10 text-center">Раздел доступен только администраторам.</p> : <>
      <div className="mb-7 flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-widest text-amber-800">Админ-центр</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-950">Управление обучением</h1></div><Link href="/faq#authoring" className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-zinc-500 hover:bg-white hover:text-zinc-800"><HelpCircle size={17} />Как работать с модулями</Link></div>
      <AdminNav />
      <ModuleLibrary />
    </>}
  </div></AppShell>;
}
