"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { AdminScreen } from "@/components/admin/admin-screen";
import { ModuleLibrary } from "@/components/admin/module-library";

export default function AdminModulesPage() {
  const params = useSearchParams();
  const router = useRouter();
  const oldModule = params.get("mid");
  const oldLesson = params.get("sid");

  useEffect(() => {
    if (oldModule) {
      router.replace(`/admin/modules/${encodeURIComponent(oldModule)}?tab=tests${oldLesson ? `&lesson=${encodeURIComponent(oldLesson)}` : ""}`);
    }
  }, [oldLesson, oldModule, router]);

  if (oldModule) {
    return <p role="status" className="p-10 text-center text-sm text-zinc-500">Открываем единый редактор модуля…</p>;
  }

  return (
    <AdminScreen title="Управление обучением" subtitle="Материалы, структура и обновления модулей — без потери результатов учеников.">
      <ModuleLibrary />
    </AdminScreen>
  );
}
