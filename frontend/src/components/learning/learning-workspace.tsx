"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, BookOpen, Check, CheckCircle2, ChevronDown, ChevronRight, Circle, FileText, Folder, GraduationCap, Loader2, Pencil, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { LessonPresentation, type PresentationLesson } from "@/components/learning/lesson-presentation";
import { AppShell } from "@/components/app/shell";
import { AssetPreviewModal } from "@/components/materials/asset-preview";
import { MaterialBrowser } from "@/components/materials/material-browser";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useAuth } from "@/lib/hooks/use-auth";
import { formatFileCount, type Material } from "@/lib/materials";

export type LessonMeta = PresentationLesson & { id: string; module_id: string; title: string; order: number; quiz_id: string; requires_quiz: boolean; is_folder: boolean; outline_path: string | null; content?: string };
type ModuleMeta = { id: string; title: string; description: string | null; is_active: boolean };
type LessonStatus = { submodule_id: string; read: boolean; passed: boolean; requires_quiz: boolean; best_score: number | null };
type ProgressData = { total: number; passed: number; completed: boolean; current_completed: boolean; completed_at: string | null; final_quiz_id: string | null; final_passed: boolean; final_best_score: number | null; submodules: LessonStatus[] };
const actionClass = "gap-2 rounded-xl text-sm font-medium normal-case tracking-normal";

export function LearningWorkspace({ moduleId, initialLessonId = "" }: { moduleId: string; initialLessonId?: string }) {
  const router = useRouter();
  const search = useSearchParams();
  const { user } = useAuth();
  const [module, setModule] = useState<ModuleMeta | null>(null);
  const [lessons, setLessons] = useState<LessonMeta[]>([]);
  const [progress, setProgress] = useState<ProgressData | null>(null);
  const [generalAssets, setGeneralAssets] = useState<Material[]>([]);
  const [lesson, setLesson] = useState<LessonMeta | null>(null);
  const [assets, setAssets] = useState<Material[]>([]);
  const [preview, setPreview] = useState<Material | null>(null);
  const [query, setQuery] = useState("");
  const [contentsOpen, setContentsOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [lessonLoading, setLessonLoading] = useState(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lessonError, setLessonError] = useState<string | null>(null);
  const [contentRefresh, setContentRefresh] = useState(0);
  const selectedId = search.get("lesson") || initialLessonId;
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";
  const loadedLesson = useRef("");

  const load = useCallback(async (signal?: AbortSignal) => {
    setError(null);
    try {
      const [meta, subs, files, state] = await Promise.all([
        apiFetch<ModuleMeta>(`/modules/${moduleId}`, { signal }),
        apiFetch<LessonMeta[]>(`/modules/${moduleId}/submodules`, { signal }),
        apiFetch<{ assets: Material[] }>(`/modules/${moduleId}/assets`, { signal }),
        apiFetch<ProgressData>(`/progress/modules/${moduleId}`, { signal }),
      ]);
      if (signal?.aborted) return;
      setModule(meta); setLessons(subs); setGeneralAssets(files.assets || []); setProgress(state);
    } catch (e) {
      if (!signal?.aborted) setError(e instanceof Error ? e.message : "Не удалось загрузить модуль");
    } finally { if (!signal?.aborted) setLoading(false); }
  }, [moduleId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, contentRefresh]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const events = new EventSource("/api/backend/modules/events");
    const refresh = () => { clearTimeout(timer); timer = setTimeout(() => setContentRefresh(n => n + 1), 250); };
    events.addEventListener("modules", refresh);
    window.addEventListener("focus", refresh);
    return () => { events.close(); clearTimeout(timer); window.removeEventListener("focus", refresh); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const changed = loadedLesson.current !== selectedId;
    loadedLesson.current = selectedId;
    if (changed) { setLesson(null); setAssets([]); setPreview(null); }
    setLessonError(null);
    if (!selectedId) { setLessonLoading(false); return () => controller.abort(); }
    if (changed) setLessonLoading(true);
    void Promise.all([
      apiFetch<LessonMeta>(`/submodules/${selectedId}`, { signal: controller.signal }),
      apiFetch<{ assets: Material[] }>(`/modules/submodules/${selectedId}/assets`, { signal: controller.signal }),
    ]).then(([meta, files]) => {
      if (controller.signal.aborted) return;
      if (meta.module_id !== moduleId) throw new Error("Этот урок относится к другому модулю");
      setLesson(meta); setAssets(files.assets || []);
      setPreview(previous => previous ? files.assets.find(a => a.asset_id === previous.asset_id) || null : null);
      if (changed) void apiFetch(`/submodules/${selectedId}/open`, { method: "POST", signal: controller.signal }).catch(() => {});
    }).catch(e => { if (!controller.signal.aborted) { setLessonError(e instanceof Error ? e.message : "Урок недоступен"); if ((e as { status?: number }).status === 404) { setLesson(null); setAssets([]); setPreview(null); } } })
      .finally(() => { if (!controller.signal.aborted) setLessonLoading(false); });
    return () => controller.abort();
  }, [selectedId, moduleId, contentRefresh]);

  // Keep the established completion behavior for modules consisting only of file catalogs.
  useEffect(() => {
    if (!module || !progress || lessons.some(l => !l.is_folder) || progress.completed) return;
    const controller = new AbortController();
    void apiFetch(`/modules/${moduleId}/open`, { method: "POST", signal: controller.signal }).then(() => load(controller.signal)).catch(() => {});
    return () => controller.abort();
  }, [module?.id, moduleId, lessons.length, progress?.completed, load]);

  const statusById = useMemo(() => new Map(progress?.submodules.map(s => [s.submodule_id, s]) || []), [progress]);
  const done = (id: string) => { const s = statusById.get(id); return !!s && (s.requires_quiz ? s.passed : s.read); };
  const currentStatus = statusById.get(selectedId);
  const visibleLessons = lessons.filter(l => `${l.outline_path || ""} ${l.title}`.toLocaleLowerCase("ru").includes(query.trim().toLocaleLowerCase("ru")));
  const nextLesson = lessons.find(l => !l.is_folder && !done(l.id)) || lessons.find(l => !l.is_folder) || lessons[0];
  const following = lessons[lessons.findIndex(l => l.id === selectedId) + 1];
  const currentAssets = selectedId ? assets : generalAssets;
  const finalReady = !!progress && (progress.completed || progress.submodules.every(s => s.requires_quiz ? s.passed : s.read));
  const percent = progress?.completed ? 100 : progress?.total ? Math.round(progress.passed / progress.total * 100) : 0;
  const lessonHref = (id: string) => `/modules/${moduleId}?lesson=${encodeURIComponent(id)}`;
  // После последнего урока путь ведёт к итоговому тесту, а не обрывается.
  const nextStep = following
    ? { href: lessonHref(following.id), title: following.title }
    : progress?.final_quiz_id && finalReady
      ? { href: `/quizzes/${progress.final_quiz_id}?module=${moduleId}`, title: progress.final_passed ? "Итоговый тест (пройден)" : "Итоговый тест" }
      : null;

  async function confirmRead() {
    if (!lesson || reading) return;
    setReading(true); setLessonError(null);
    try {
      await apiFetch(`/submodules/${lesson.id}/read`, { method: "POST" });
      await load();
      window.dispatchEvent(new Event("corelms:modules-updated"));
      window.dispatchEvent(new CustomEvent("corelms:refresh-me", { detail: { reason: "progress" } }));
    } catch (e) { setLessonError(e instanceof Error ? e.message : "Не удалось сохранить прогресс"); }
    finally { setReading(false); }
  }

  function openAsset(asset: Material) { setPreview(asset); }

  return <AppShell>
    <div className="mx-auto w-full max-w-[1440px] px-4 py-7 sm:px-6 lg:py-10">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <Link href="/modules" className="inline-flex items-center gap-2 text-sm text-zinc-500 hover:text-zinc-900"><ArrowLeft size={16} />Все модули</Link>
        {isAdmin && <Link href={`/admin/modules/${moduleId}${selectedId ? `?lesson=${encodeURIComponent(selectedId)}` : ""}`} className="inline-flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs font-medium text-zinc-700 hover:border-amber-400"><Pencil size={14} />Редактировать модуль</Link>}
      </div>
      {loading ? <div role="status" className="flex min-h-80 items-center justify-center gap-3 text-zinc-500"><Loader2 className="animate-spin" />Загружаем материалы…</div> : !module ? <div role="alert" className="rounded-2xl border border-rose-200 bg-white p-8"><h1 className="text-xl font-semibold">Модуль недоступен</h1><p className="mt-2 text-sm text-zinc-600">{error || "Он мог быть перемещён в архив или доступ к нему изменён."}</p><Button className={`mt-4 ${actionClass}`} onClick={() => void load()}>Повторить</Button></div> : <>
        <header className="mb-7 flex flex-wrap items-end justify-between gap-5">
          <div className="max-w-4xl"><p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-amber-700">Учебный модуль {!module.is_active && "· Предпросмотр черновика"}</p><h1 className="text-2xl font-semibold leading-tight tracking-tight text-zinc-950 sm:text-3xl">{module.title}</h1></div>
          <div className="min-w-52"><div className="mb-2 flex justify-between gap-5 text-xs"><span className={progress?.completed ? "font-medium text-emerald-700" : "text-zinc-500"}>{progress?.completed ? "Обучение завершено" : "Ваш прогресс"}</span><span className="font-semibold tabular-nums">{percent}%</span></div><div className="h-1.5 overflow-hidden rounded-full bg-zinc-200" role="progressbar" aria-label="Прогресс модуля" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}><div className="h-full rounded-full bg-emerald-700 transition-all" style={{ width: `${percent}%` }} /></div></div>
        </header>
        {error && <p role="alert" className="mb-4 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">{error}</p>}
        {progress?.completed && !progress.current_completed && <div className="mb-6 flex gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm leading-relaxed text-emerald-900"><ShieldCheck size={20} className="mt-0.5 shrink-0" /><div><strong>Ваш результат сохранён.</strong> После прохождения модуль обновили. Новые материалы доступны для ознакомления — повторно проходить обучение не нужно.</div></div>}
        <div className="grid items-start gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
          <aside className="rounded-2xl border border-zinc-200 bg-white lg:sticky lg:top-24">
            <div className="border-b border-zinc-100 p-4"><div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold">Содержание</h2><div className="flex items-center gap-3"><span className="text-xs text-zinc-400">{lessons.length}</span><button type="button" aria-expanded={contentsOpen} aria-controls="learning-contents" onClick={() => setContentsOpen(v => !v)} className="flex items-center gap-1 text-xs font-medium text-amber-800 lg:hidden">{contentsOpen ? "Свернуть" : "Открыть"}<ChevronDown size={15} className={contentsOpen ? "rotate-180" : ""} /></button></div></div><label className={cn("flex items-center gap-2 rounded-lg bg-zinc-50 px-2.5 text-zinc-400", !contentsOpen && "hidden lg:flex")}><Search size={15} /><input aria-label="Поиск по содержанию" placeholder="Найти урок…" value={query} onChange={e => setQuery(e.target.value)} className="h-9 w-full min-w-0 bg-transparent text-xs text-zinc-700 outline-none" /></label></div>
            <nav id="learning-contents" aria-label="Содержание модуля" className={cn("max-h-[65vh] space-y-1 overflow-y-auto p-2", !contentsOpen && "hidden lg:block")}>
              <Link onClick={() => setContentsOpen(false)} href={`/modules/${moduleId}`} aria-current={!selectedId ? "page" : undefined} className={cn("flex items-center gap-3 rounded-xl px-3 py-3 text-sm", !selectedId ? "bg-amber-50 font-medium text-amber-900" : "text-zinc-600 hover:bg-zinc-50")}><BookOpen size={18} className="shrink-0" />Обзор и общие файлы</Link>
              {visibleLessons.map((item, i) => <Link key={item.id} onClick={() => setContentsOpen(false)} href={lessonHref(item.id)} aria-current={selectedId === item.id ? "page" : undefined} className={cn("flex items-start gap-3 rounded-xl px-3 py-3 text-sm transition-colors", selectedId === item.id ? "bg-amber-50 font-medium text-zinc-950" : "text-zinc-600 hover:bg-zinc-50")}>
                <span className={cn("mt-0.5 shrink-0", done(item.id) ? "text-emerald-700" : "text-zinc-400")}>{item.is_folder ? <Folder size={18} /> : done(item.id) ? <CheckCircle2 size={18} /> : <Circle size={18} />}</span>
                <span className="min-w-0 break-words"><span className="block leading-5">{item.title}</span>{item.outline_path && <span className="mt-1 block text-[11px] font-normal text-zinc-400">{item.outline_path}</span>}<span className="mt-1 block text-[11px] font-normal text-zinc-400">{item.is_folder ? "Каталог файлов" : item.requires_quiz ? "Урок с тестом" : "Материал для изучения"}</span></span>
              </Link>)}
              {!visibleLessons.length && query && <p className="p-4 text-xs text-zinc-500">Уроки не найдены.</p>}
            </nav>
            {progress?.final_quiz_id && <div className="border-t border-zinc-100 p-3">{finalReady ? <Link href={`/quizzes/${progress.final_quiz_id}?module=${moduleId}`} className="flex items-center gap-3 rounded-xl bg-emerald-50 px-3 py-3 text-sm font-medium text-emerald-900"><GraduationCap size={20} />{progress.final_passed ? `Итоговый тест · ${progress.final_best_score}%` : "Пройти итоговый тест"}<ChevronRight size={15} className="ml-auto" /></Link> : <p className="flex items-start gap-2 px-2 py-2 text-xs leading-relaxed text-zinc-500"><GraduationCap size={18} className="shrink-0" />Итоговый тест откроется после завершения уроков.</p>}</div>}
          </aside>
          <section className="min-w-0 space-y-5">
            {selectedId && lessonLoading ? <div role="status" className="flex min-h-64 items-center justify-center gap-3 rounded-2xl border border-zinc-200 bg-white text-sm text-zinc-500"><Loader2 className="animate-spin" />Загружаем урок…</div> : selectedId && !lesson ? <div className="rounded-2xl border border-zinc-200 bg-white p-8"><h2 className="text-xl font-semibold">Материал недоступен</h2><p role="alert" className="mt-3 text-sm text-zinc-500">{lessonError || "Выберите другой урок в содержании."}</p><Button variant="outline" className={`mt-4 ${actionClass}`} onClick={() => setContentRefresh(n => n + 1)}><RefreshCw size={16} />Повторить</Button></div> : <>
              <section className="rounded-2xl border border-zinc-200 bg-white p-5 sm:p-7">
                <div className="mb-5 flex flex-wrap items-center justify-between gap-3"><div><p className="mb-2 text-xs text-zinc-500">{lesson ? lesson.is_folder ? "Каталог материалов" : `Урок ${lessons.filter(l => !l.is_folder).findIndex(l => l.id === lesson.id) + 1}` : "Добро пожаловать в модуль"}</p><h2 className="text-xl font-semibold tracking-tight text-zinc-950 sm:text-2xl">{lesson?.title || "Учитесь в удобном темпе"}</h2></div>{lesson && done(lesson.id) && <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700"><Check size={14} />{currentStatus?.best_score != null ? `Пройдено · ${currentStatus.best_score}%` : "Изучено"}</span>}</div>
                {!lesson && <div className="space-y-5"><p className="text-sm leading-7 text-zinc-600">{module.description || "Изучайте уроки и открывайте материалы прямо здесь. Прогресс сохраняется автоматически после подтверждения прочтения и прохождения тестов."}</p>{nextLesson && <Button asChild className={actionClass}><Link href={lessonHref(nextLesson.id)}>{progress?.completed ? "Повторить материалы" : progress?.passed ? "Продолжить обучение" : "Начать обучение"}<ArrowRight size={17} /></Link></Button>}<div className="flex flex-wrap gap-5 border-t border-zinc-100 pt-4 text-xs text-zinc-500"><span>{lessons.filter(l => !l.is_folder).length} уроков</span><span>{lessons.filter(l => l.is_folder).length} каталогов</span><span>{generalAssets.length} общих файлов</span><span className="flex items-center gap-1.5"><ShieldCheck size={14} />Результаты не теряются при обновлении модуля</span></div></div>}
                {lesson?.is_folder && <p className="text-sm leading-relaxed text-zinc-500">Откройте нужный файл ниже. Для таблиц доступен просмотр листов, для работы с формулами скачайте оригинал.</p>}

              </section>
              {lesson && !lesson.is_folder && <LessonPresentation key={lesson.id} lesson={lesson} assets={assets} />}
              {(!lesson || lesson.is_folder) && (currentAssets.length > 0 || lesson?.is_folder) && <section className="rounded-2xl border border-zinc-200 bg-white p-4 sm:p-6"><div className="mb-4 flex items-center justify-between"><h2 className="flex items-center gap-2 text-sm font-semibold"><FileText size={17} className="text-zinc-400" />{lesson ? "Файлы урока" : "Общие материалы"}</h2><span className="text-xs text-zinc-400">{formatFileCount(currentAssets.length)}</span></div><MaterialBrowser key={selectedId || "general"} materials={currentAssets} onSelect={openAsset} selectedId={preview?.asset_id} /></section>}
              
              {lesson && !lesson.is_folder && <section className="rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6">
                {lessonError && <p role="alert" className="mb-4 text-sm text-rose-700">{lessonError}</p>}
                <div className="flex flex-wrap items-center justify-between gap-4"><div><h3 className="text-sm font-semibold">{currentStatus?.read ? "Прочтение сохранено" : "Готовы двигаться дальше?"}</h3><p className="mt-1 text-xs leading-relaxed text-zinc-500">{lesson.requires_quiz ? "Подтвердите изучение материала, затем пройдите тест." : "Подтвердите изучение, чтобы сохранить результат урока."}</p></div><div className="flex flex-wrap items-center gap-2"><Button variant={currentStatus?.read ? "outline" : "primary"} className={actionClass} disabled={reading || currentStatus?.read} onClick={() => void confirmRead()}>{reading ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}{currentStatus?.read ? "Материал изучен" : "Я изучил материал"}</Button>{lesson.requires_quiz && <Button disabled={!currentStatus?.read} className={actionClass} onClick={() => router.push(`/quizzes/${lesson.quiz_id}?module=${moduleId}&submodule=${lesson.id}`)}>{currentStatus?.passed ? "Результат теста" : "Перейти к тесту"}<ArrowRight size={16} /></Button>}</div></div>
                {nextStep && <div className="mt-5 border-t border-zinc-100 pt-4"><Link href={nextStep.href} className="flex items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-sm text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900"><span className="min-w-0"><span className="mb-1 block text-[11px] text-zinc-400">Далее</span><span className="block truncate">{nextStep.title}</span></span><ArrowRight size={18} className="shrink-0" /></Link></div>}
              </section>}
            </>}
          </section>
        </div>
      </>}
      <AssetPreviewModal asset={preview} onClose={() => setPreview(null)} />
    </div>
  </AppShell>;
}
