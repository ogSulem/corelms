"use client";

import { formatFileCount } from "@/lib/materials";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Archive, ArrowRight, BookOpen, FilePlus2, Folder, Loader2, Plus, RefreshCw, RotateCcw, Search, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/cn";
import { throttleRefresh } from "@/lib/refresh-throttle";

type LibraryModule = { id: string; title: string; description?: string | null; category?: string | null; is_active: boolean; is_archived: boolean; content_revision: number; lesson_count: number; asset_count: number };
const btn = "gap-2 rounded-xl text-sm font-medium normal-case tracking-normal";

export function ModuleLibrary() {
  const router = useRouter();
  const [items, setItems] = useState<LibraryModule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    try {
      const result = await apiFetch<{ items: LibraryModule[] }>("/admin/content/modules?include_archived=true", { signal: controller.signal });
      if (!controller.signal.aborted) { setItems(result.items); setError(null); }
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Не удалось загрузить список модулей"); }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }, []);
  useEffect(() => {
    void load();
    const focus = () => { void load(); };
    const events = new EventSource("/api/backend/modules/events");
    events.addEventListener("modules", focus);
    // Живые события уже обновляют список; возврат на вкладку — не чаще раза в минуту.
    const onFocus = throttleRefresh(focus);
    window.addEventListener("focus", onFocus);
    return () => { request.current?.abort(); events.close(); window.removeEventListener("focus", onFocus); };
  }, [load]);
  const filtered = useMemo(() => items.filter(m => filter === "archive" ? m.is_archived : !m.is_archived && (filter === "all" || (filter === "published" ? m.is_active : !m.is_active)))
    .filter(m => `${m.title} ${m.category || ""}`.toLocaleLowerCase("ru").includes(query.trim().toLocaleLowerCase("ru")))
    .sort((a, b) => a.title.localeCompare(b.title, "ru", { numeric: true })), [items, filter, query]);

  async function create() {
    if (busy || !title.trim()) return;
    setBusy(true); setError(null);
    try {
      const result = await apiFetch<{ module: { id: string } }>("/admin/content/modules", { method: "POST", body: JSON.stringify({ title: title.trim() }) });
      setCreating(false); router.push(`/admin/modules/${result.module.id}`);
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось создать модуль"); }
    finally { setBusy(false); }
  }
  async function restore(module: LibraryModule) {
    setBusy(true); setError(null);
    try {
      await apiFetch(`/admin/content/modules/${module.id}`, { method: "PATCH", body: JSON.stringify({ revision: module.content_revision, is_archived: false }) });
      await load();
      window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "Модуль восстановлен", description: "Модуль в черновиках. Опубликуйте его после проверки." } }));
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось восстановить модуль"); }
    finally { setBusy(false); }
  }

  return <div className="space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-4"><div><h2 className="text-xl font-semibold tracking-tight">Библиотека модулей</h2><p className="mt-1.5 text-sm text-zinc-500">Материалы, структура и обновления — без потери результатов учеников.</p></div><div className="flex flex-wrap gap-2"><Button variant="outline" asChild className={btn}><Link href="/admin/import"><FilePlus2 size={16} />Импорт нового ZIP</Link></Button><Button onClick={() => { setTitle(""); setError(null); setCreating(true); }} className={btn}><Plus size={17} />Создать модуль</Button></div></div>
    {error && !creating && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</p>}
    <div className="rounded-2xl border border-zinc-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200 p-4"><div className="flex flex-wrap gap-1">{[{ id: "all", label: "Все модули", count: items.filter(m => !m.is_archived).length }, { id: "published", label: "Опубликованы", count: items.filter(m => !m.is_archived && m.is_active).length }, { id: "drafts", label: "Черновики", count: items.filter(m => !m.is_archived && !m.is_active).length }, { id: "archive", label: "Архив", count: items.filter(m => m.is_archived).length }].map(tab => <button type="button" key={tab.id} aria-pressed={filter === tab.id} onClick={() => setFilter(tab.id)} className={cn("flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium", filter === tab.id ? "bg-amber-50 text-amber-900" : "text-zinc-500 hover:bg-zinc-50")}>{tab.id === "archive" && <Archive size={13} />}{tab.label}<span className="text-[10px] opacity-60">{tab.count}</span></button>)}</div><div className="flex min-w-52 flex-1 items-center gap-2 sm:max-w-sm"><label className="flex flex-1 items-center gap-2 rounded-lg border border-zinc-200 px-3 text-zinc-400"><Search size={16} /><input aria-label="Поиск модулей" value={query} onChange={e => setQuery(e.target.value)} placeholder="Название или категория…" className="h-10 w-full min-w-0 bg-transparent text-sm text-zinc-800 outline-none" /></label><button type="button" title="Обновить список" aria-label="Обновить список модулей" onClick={() => { setError(null); void load(); }} className="rounded-lg p-2 text-zinc-400 hover:bg-zinc-100"><RefreshCw size={16} /></button></div></div>
      {loading ? <div role="status" className="flex min-h-64 items-center justify-center gap-2 text-sm text-zinc-500"><Loader2 size={20} className="animate-spin" />Загружаем библиотеку…</div> : error && !items.length ? <div className="p-12 text-center text-sm text-zinc-500"><p>Библиотека не загружена. Модули не были изменены.</p><Button variant="outline" className={`mt-4 ${btn}`} onClick={() => void load()}><RefreshCw size={15} />Повторить загрузку</Button></div> : filtered.length ? <div className="divide-y divide-zinc-100">{filtered.map(module => <article key={module.id} className="flex flex-wrap items-center gap-4 p-5 transition-colors hover:bg-zinc-50/50"><div className={cn("flex h-12 w-12 shrink-0 items-center justify-center rounded-xl", module.is_archived ? "bg-zinc-100 text-zinc-400" : "bg-amber-50 text-amber-700")}>{module.is_archived ? <Archive size={22} /> : <BookOpen size={22} />}</div><div className="min-w-0 flex-1 basis-52"><div className="mb-1.5 flex flex-wrap items-center gap-2"><span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", module.is_archived ? "bg-zinc-100 text-zinc-500" : module.is_active ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800")}>{module.is_archived ? "Архив" : module.is_active ? "Опубликован" : "Черновик"}</span>{module.category && <span className="text-xs text-zinc-400">{module.category}</span>}</div><Link href={`/admin/modules/${module.id}`} className="break-words text-base font-semibold text-zinc-800 hover:text-amber-800">{module.title}</Link><p className="mt-1.5 text-xs text-zinc-400">{module.lesson_count} материалов в структуре · {formatFileCount(module.asset_count)} · Редакция {module.content_revision}</p></div><div className="flex flex-wrap items-center gap-2">{module.is_archived ? <Button variant="outline" size="sm" className={btn} disabled={busy} onClick={() => void restore(module)}><RotateCcw size={14} />Восстановить</Button> : null}<Button variant="outline" asChild className={btn}><Link href={`/admin/modules/${module.id}`}>{module.is_archived ? "Открыть" : "Редактировать"}<ArrowRight size={15} /></Link></Button></div></article>)}</div> : <div className="py-16 text-center"><Folder size={36} className="mx-auto mb-4 text-zinc-300" /><h3 className="text-base font-medium text-zinc-700">{query ? "Модули не найдены" : filter === "archive" ? "Архив пока пуст" : filter === "drafts" ? "Черновиков пока нет" : filter === "published" ? "Нет опубликованных модулей" : "Здесь пока нет модулей"}</h3><p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-zinc-400">{query ? "Попробуйте изменить запрос или фильтр." : filter === "archive" ? "Архивные модули сохраняют файлы и историю обучения." : filter === "published" ? "Проверьте материалы в черновике и опубликуйте модуль в его редакторе." : "Создайте модуль с нуля или импортируйте подготовленный ZIP."}</p></div>}
    </div>
    <p className="flex items-start gap-2 text-xs leading-relaxed text-zinc-500"><ShieldCheck size={16} className="shrink-0 text-emerald-700" />Чтобы обновить существующий модуль, откройте его редактор → «Обновить из ZIP». Удалять модуль перед обновлением не нужно.</p>
    <Modal open={creating} title="Новый модуль" onClose={() => { if (!busy) setCreating(false); }} disableClose={busy} className="max-w-lg" footer={<div className="flex justify-end gap-2"><Button variant="ghost" className={btn} onClick={() => setCreating(false)} disabled={busy}>Отмена</Button><Button className={btn} disabled={busy || !title.trim()} onClick={() => void create()}>{busy ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}Создать</Button></div>}>
      <form onSubmit={e => { e.preventDefault(); void create(); }}><label className="block text-sm font-medium">Название модуля<input autoFocus required maxLength={300} value={title} onChange={e => setTitle(e.target.value)} placeholder="Например, Расчёт себестоимости" className="mt-2 w-full rounded-xl border border-zinc-200 px-4 py-3 text-sm outline-none focus:border-amber-500" /></label><p className="mt-3 text-xs leading-relaxed text-zinc-500">Модуль будет создан как черновик. Добавьте уроки и файлы, затем опубликуйте его.</p>{error && <p role="alert" className="mt-4 text-sm text-rose-700">{error}</p>}</form>
    </Modal>
  </div>;
}
