"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight, BookOpen, CheckCircle2, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";

type NextStep = {
  state: "start" | "continue" | "updates" | "completed" | "empty";
  modules_total: number;
  modules_completed: number;
  next: null | {
    module_id: string; module_title: string; submodule_title: string | null;
    kind: "lesson" | "quiz" | "final_quiz" | "materials";
    href: string; label: string; passed: number; total: number; completed: boolean;
  };
};

export function ContinueCard() {
  const [data, setData] = useState<NextStep | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setLoading(true); setError(null);
    try {
      const next = await apiFetch<NextStep>("/linear/next-unlocked-resolved", { signal: controller.signal });
      if (!controller.signal.aborted) setData(next);
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Не удалось загрузить следующий шаг");
    } finally { if (!controller.signal.aborted) setLoading(false); }
  }, []);
  useEffect(() => {
    void load();
    const refresh = (event: Event) => {
      if ((event as CustomEvent).detail?.reason !== "keepalive") void load();
    };
    window.addEventListener("corelms:refresh-me", refresh);
    return () => { request.current?.abort(); window.removeEventListener("corelms:refresh-me", refresh); };
  }, [load]);

  const next = data?.next;
  const complete = data?.state === "completed";
  const updated = data?.state === "updates";
  const percent = next?.total ? Math.min(100, Math.round(100 * next.passed / next.total)) : 0;

  return <section aria-label="Следующий шаг обучения" className="relative flex h-full min-h-72 flex-col justify-between gap-7 rounded-[28px] border border-zinc-200 bg-white/90 p-6 shadow-xl shadow-zinc-950/5 sm:p-8" aria-busy={loading}>
    {loading && !data ? <div role="status" className="flex flex-1 items-center justify-center gap-3 text-sm text-zinc-500"><Loader2 size={22} className="animate-spin" />Находим следующий шаг…</div> : error ? <div className="space-y-5"><div className="text-sm font-semibold text-zinc-900">Не удалось загрузить обучение</div><p role="alert" className="text-sm leading-6 text-zinc-600">{error}</p><Button variant="outline" onClick={() => void load()} className="gap-2 rounded-xl text-sm font-medium normal-case tracking-normal"><RefreshCw size={16} />Повторить</Button></div> : <>
      <div>
        <div className="mb-4 flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-amber-800">{complete ? <CheckCircle2 size={18} className="text-emerald-700" /> : updated ? <Sparkles size={18} /> : <BookOpen size={18} />}{complete ? "Отличная работа" : updated ? "Новые материалы" : data?.state === "continue" ? "Продолжить обучение" : "Ваше обучение"}</div>
        <h3 className="break-words text-2xl font-semibold leading-tight tracking-tight text-zinc-950">{next?.module_title || (complete ? "Все доступные модули пройдены" : "Материалы пока не назначены")}</h3>
        <p className="mt-3 text-sm leading-6 text-zinc-500">{next ? updated ? "Ваш результат сохранён. Познакомьтесь с обновлёнными материалами в удобном темпе." : next.kind === "final_quiz" ? "Уроки пройдены. Остался итоговый тест модуля." : next.submodule_title ? `Следующий шаг: ${next.submodule_title}` : "Откройте файлы и инструкции этого модуля." : complete ? `Пройдено модулей: ${data?.modules_completed} из ${data?.modules_total}. Материалы остаются доступны для повторения.` : "Опубликованные для вас модули появятся здесь. Если ожидаете доступ, обратитесь к администратору."}</p>
      </div>
      <div className="space-y-5">
        {next && next.total > 0 && <div><div className="mb-2 flex justify-between gap-3 text-xs text-zinc-500"><span>{updated ? "Шаги в текущей редакции" : "Завершено шагов"}</span><span className="font-medium tabular-nums text-zinc-800">{next.passed} / {next.total}</span></div><div role="progressbar" aria-label="Прогресс текущей редакции" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} className="h-1.5 overflow-hidden rounded-full bg-zinc-100"><div className="h-full rounded-full bg-amber-500 transition-all" style={{ width: `${percent}%` }} /></div></div>}
        <Button asChild className="h-12 w-full gap-2 rounded-xl text-sm font-semibold normal-case tracking-normal"><Link href={next?.href || "/modules"}>{next?.label || (complete ? "Повторить материалы" : "Открыть каталог")}<ArrowRight size={17} /></Link></Button>
      </div>
    </>}
  </section>;
}
