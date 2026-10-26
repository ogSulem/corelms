"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { BookOpen, CheckCircle2, ExternalLink, FileSpreadsheet, Image, Link2, Loader2, PlayCircle, RefreshCw, Search } from "lucide-react";
import { AppShell } from "@/components/app/shell";
import { SalesFileLibrary } from "@/components/materials/sales-file-library";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useActiveTabVisibility } from "@/lib/hooks/use-active-tab-visibility";
import { useAuth } from "@/lib/hooks/use-auth";

type SalesLink = { title: string; url: string };
type Block = { id: string; title: string; kind: "links" | "video"; links?: SalesLink[]; tabs?: { id: string; label: string; links: SalesLink[] }[] };
type SheetData = { blocks: Block[]; status: "fresh" | "stale" | "loading" | "error" | "unconfigured"; last_success_at: string | null; warnings: string[]; source_url: string | null; message: string | null; refreshing?: boolean };
const btn = "gap-2 rounded-xl text-sm font-medium normal-case tracking-normal";

function safeUrl(value: string) {
  if (/\s|\\|[\u0000-\u001f\u007f]/.test(value)) return false;
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) && !!url.hostname && !url.username && !url.password; } catch { return false; }
}
function LinksBlock({ block, query }: { block: Block; query: string }) {
  const [selected, setSelected] = useState(block.tabs?.[0]?.id || "");
  const tab = block.tabs?.find(t => t.id === selected) || block.tabs?.[0];
  const needle = query.trim().toLocaleLowerCase("ru");
  const searchAll = !!needle && !block.title.toLocaleLowerCase("ru").includes(needle);
  const all = block.kind === "video" ? searchAll ? (block.tabs || []).flatMap(t => t.links.map(link => ({ ...link, group: t.label }))) : tab?.links || [] : block.links || [];
  const links = all.filter(link => safeUrl(link.url) && (!searchAll || `${link.title} ${"group" in link ? link.group : ""}`.toLocaleLowerCase("ru").includes(needle)));
  if (needle && !links.length) return null;
  return <section className="space-y-4 rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6"><div className="flex items-center gap-2.5"><span className="rounded-xl bg-amber-50 p-2.5 text-amber-700">{block.kind === "video" ? <PlayCircle size={20} /> : <Link2 size={20} />}</span><h2 className="min-w-0 break-words text-lg font-semibold">{block.title}</h2><span className="ml-auto text-xs text-zinc-400">{links.length}</span></div>
    {block.kind === "video" && !searchAll && !!block.tabs?.length && <div aria-label={`Разделы: ${block.title}`} className="flex flex-wrap gap-2">{block.tabs.map(t => <button key={t.id} type="button" aria-pressed={tab?.id === t.id} onClick={() => setSelected(t.id)} className={cn("rounded-lg border px-3 py-2 text-xs font-medium", tab?.id === t.id ? "border-amber-200 bg-amber-50 text-amber-900" : "border-zinc-200 text-zinc-500 hover:bg-zinc-50")}>{t.label}</button>)}</div>}
    {links.length ? <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-3">{links.map((link, i) => <a key={`${link.url}:${i}`} href={link.url} target="_blank" rel="noopener noreferrer" className="group flex min-w-0 items-start gap-3 rounded-xl border border-zinc-200 p-4 transition-colors hover:border-amber-300 hover:bg-amber-50/40"><div className="min-w-0 flex-1"><span className="block break-words text-sm font-medium leading-6 text-zinc-800">{link.title}</span><span className="mt-1 block truncate text-[11px] text-zinc-400">{"group" in link ? `${String(link.group)} · ` : ""}{new URL(link.url).hostname} · новая вкладка</span></div><ExternalLink size={15} className="mt-1 shrink-0 text-zinc-400 group-hover:text-amber-700" /></a>)}</div> : <p className="py-4 text-sm text-zinc-400">В этом разделе пока нет корректных ссылок.</p>}
  </section>;
}

export default function SalesPage() {
  return <Suspense fallback={<AppShell><p role="status" className="p-12 text-center text-sm text-zinc-500">Загружаем материалы продаж…</p></AppShell>}><SalesWorkspace /></Suspense>;
}

function SalesWorkspace() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter(), params = useSearchParams();
  const section = params.get("section") === "photos" ? "photos" : params.get("section") === "catalogs" ? "catalogs" : "links";
  const tabsRef = useActiveTabVisibility(section);
  const path = section === "links" ? "" : params.get("path") || "";
  const canManage = user?.role === "superadmin";
  const [sheets, setSheets] = useState<SheetData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const retry = useRef(0);

  const refreshSheets = useCallback(async (force = false, signal?: AbortSignal) => {
    setLoading(true); setError(null);
    try {
      const next = await apiFetch<SheetData>(`/sales-links${force ? "?bypass_cache=true" : ""}`, { signal });
      if (!signal?.aborted) setSheets(next);
    } catch (e) { if (!signal?.aborted) setError(e instanceof Error ? e.message : "Не удалось получить ссылки"); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, []);
  useEffect(() => {
    if (!user) return;
    const controller = new AbortController();
    void refreshSheets(false, controller.signal);
    return () => controller.abort();
  }, [user?.id, refreshSheets]);
  useEffect(() => {
    if (!sheets?.refreshing || retry.current > 10) return;
    const controller = new AbortController();
    const timer = setTimeout(() => { retry.current += 1; void refreshSheets(false, controller.signal); }, 5000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [sheets, refreshSheets]);
  function navigate(nextSection: string, nextPath = "") {
    if (!window.dispatchEvent(new Event("corelms:before-navigate", { cancelable: true }))) return;
    router.push(`/sales${nextSection === "links" ? "" : `?section=${nextSection}${nextPath ? `&path=${encodeURIComponent(nextPath)}` : ""}`}`);
  }
  const matching = (sheets?.blocks || []).filter(b => !query.trim() || `${b.title} ${(b.links || []).map(l => l.title).join(" ")} ${(b.tabs || []).map(t => `${t.label} ${t.links.map(l => l.title).join(" ")}`).join(" ")}`.toLocaleLowerCase("ru").includes(query.trim().toLocaleLowerCase("ru")));

  return <AppShell><div className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:py-10">
    <header className="mb-7"><p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-amber-700">Рабочая библиотека</p><h1 className="text-3xl font-semibold tracking-tight text-zinc-950">Материалы для продаж</h1><p className="mt-3 max-w-2xl text-sm leading-7 text-zinc-500">Полезные ссылки, видео, фотографии и каталоги. Ссылки обновляются из Google Sheets, файлы хранятся в библиотеке платформы.</p></header>
    <nav ref={tabsRef} aria-label="Разделы продаж" className="mb-6 flex gap-2 overflow-x-auto pb-1">{([{ id: "links", title: "Ссылки и видео", Icon: Link2 }, { id: "photos", title: "Фото", Icon: Image }, { id: "catalogs", title: "Каталоги", Icon: BookOpen }] as const).map(({ id, title, Icon }) => <button key={id} type="button" aria-current={section === id ? "page" : undefined} onClick={() => navigate(id)} className={cn("flex shrink-0 items-center gap-2 rounded-xl border px-4 py-3 text-sm font-medium", section === id ? "border-amber-200 bg-amber-50 text-amber-900" : "border-zinc-200 bg-white text-zinc-500 hover:border-zinc-300")}><Icon size={17} />{title}</button>)}</nav>
    {authLoading ? <p role="status" className="py-16 text-center text-sm text-zinc-500">Проверяем доступ…</p> : !user ? <p className="py-16 text-center text-sm text-zinc-500">Войдите в аккаунт, чтобы открыть материалы.</p> : section !== "links" ? <SalesFileLibrary key={`${section}:${path}`} section={section} path={path} canManage={canManage} onNavigate={next => navigate(section, next)} /> : <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-zinc-200 bg-white px-4 py-3"><div className="flex items-start gap-2.5"><FileSpreadsheet size={18} className="mt-1 shrink-0 text-emerald-700" /><div><p className="text-xs font-medium text-zinc-700">{sheets?.status === "fresh" ? "Данные Google Sheets получены" : sheets?.status === "stale" ? "Сохранённая копия Google Sheets" : sheets?.status === "unconfigured" ? "Google Sheets не настроены" : "Источник: Google Sheets"}</p><p className="mt-1 text-[11px] leading-5 text-zinc-400">{sheets?.last_success_at ? `Последнее успешное обновление: ${new Date(sheets.last_success_at).toLocaleString("ru-RU")}` : "Файлы в соседних вкладках работают независимо от таблицы"}</p></div></div><div className="flex flex-wrap items-center gap-2">{canManage && sheets?.status === "unconfigured" && <Link href="/admin/settings" className="inline-flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900 hover:bg-amber-100">Настроить таблицу</Link>}{canManage && sheets?.source_url && safeUrl(sheets.source_url) && <a href={sheets.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-lg border border-zinc-200 px-3 py-2 text-xs font-medium text-zinc-600 hover:bg-zinc-50">Редактировать таблицу<ExternalLink size={13} /></a>}<Button variant="ghost" size="sm" className={btn} disabled={loading} onClick={() => { retry.current = 0; void refreshSheets(canManage); }}>{loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}Обновить</Button></div></div>
      {error && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm leading-7 text-rose-800">{error}{sheets?.blocks.length ? " Ниже осталась последняя загруженная копия." : ""}</p>}
      {sheets?.message && <p role={sheets.status === "error" ? "alert" : "status"} className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-900">{sheets.message}</p>}
      {canManage && !!sheets?.warnings.length && <details className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-6 text-amber-900"><summary className="cursor-pointer font-medium">Что проверить в таблице · {sheets.warnings.length}</summary><ul className="mt-2 list-inside list-disc space-y-1">{sheets.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul></details>}
      {loading && !sheets && <p role="status" className="flex items-center justify-center gap-2 py-16 text-sm text-zinc-500"><Loader2 size={20} className="animate-spin" />Получаем ссылки…</p>}
      {!!sheets?.blocks.length && <label className="flex items-center gap-2 rounded-xl border border-zinc-200 bg-white px-4 text-zinc-400"><Search size={17} /><input aria-label="Поиск ссылок продаж" maxLength={200} className="h-12 w-full min-w-0 bg-transparent text-sm text-zinc-800 outline-none" value={query} onChange={e => setQuery(e.target.value)} placeholder="Найти документ, видео или раздел…" /></label>}
      {matching.map(block => <LinksBlock key={block.id} block={block} query={query} />)}
      {!loading && sheets?.status === "fresh" && !sheets.blocks.length && <div className="rounded-2xl border border-zinc-200 bg-white p-10 text-center"><CheckCircle2 size={28} className="mx-auto mb-3 text-emerald-600" /><h2 className="text-base font-semibold">Таблица подключена</h2><p className="mt-2 text-sm leading-7 text-zinc-500">Опубликованных разделов пока нет. Добавьте лист со столбцами name/link или tab/name/link.</p></div>}
      {query && !matching.length && <p className="py-10 text-center text-sm text-zinc-500">По вашему запросу ничего не найдено.</p>}
      {canManage && <p className="text-xs leading-6 text-zinc-400">Изменяйте названия и адреса в Google Sheets. После редактирования нажмите «Обновить»; без ручного обновления кеш действует до 3 минут. Настройка доступа к самой таблице выполняется в Google.</p>}
    </div>}
  </div></AppShell>;
}
