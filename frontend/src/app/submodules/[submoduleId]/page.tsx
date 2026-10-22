"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { LearningWorkspace, type LessonMeta } from "@/components/learning/learning-workspace";
import { AppShell } from "@/components/app/shell";
import { apiFetch } from "@/lib/api";

// Preserve old deep links while sharing the same learner experience and viewer.
export default function SubmodulePage() {
  const { submoduleId } = useParams<{ submoduleId: string }>();
  const [lesson, setLesson] = useState<LessonMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setLesson(null); setError(null);
    void apiFetch<LessonMeta>(`/submodules/${submoduleId}`, { signal: controller.signal }).then(setLesson).catch(e => {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Материал недоступен");
    });
    return () => controller.abort();
  }, [submoduleId]);
  if (!lesson) return <AppShell><div className="mx-auto max-w-xl p-10"><p role={error ? "alert" : "status"} className="text-zinc-600">{error || "Загружаем урок…"}</p>{error && <Link href="/modules" className="mt-4 inline-block text-sm text-amber-700 underline">Вернуться к модулям</Link>}</div></AppShell>;
  return <Suspense fallback={<p className="p-10">Загрузка…</p>}><LearningWorkspace key={lesson.module_id} moduleId={lesson.module_id} initialLessonId={submoduleId} /></Suspense>;
}
