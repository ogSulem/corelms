"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";
import { LearningWorkspace } from "@/components/learning/learning-workspace";

export default function ModulePage() {
  const { moduleId } = useParams<{ moduleId: string }>();
  return <Suspense fallback={<p role="status" className="p-10 text-center text-zinc-500">Загрузка модуля…</p>}><LearningWorkspace key={moduleId} moduleId={moduleId} /></Suspense>;
}
