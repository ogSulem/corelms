"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Archive, ArrowLeft, ChevronRight, Download, Folder, FolderPlus, History, Loader2, MoreHorizontal, Pencil, RefreshCw, RotateCcw, Search, ShieldCheck, UploadCloud } from "lucide-react";
import { AssetPreview } from "./asset-preview";
import { MaterialIcon } from "./material-browser";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/cn";
import { downloadMaterial, formatBytes, uploadMaterial, type Material } from "@/lib/materials";
import { AssetVersionList, type AssetVersion } from "./asset-version-list";
import { useLeaveGuard } from "@/lib/hooks/use-leave-guard";

type Entry = { id: string; name: string; kind: "folder" | "file"; path: string; is_archived: boolean; asset: Material | null };
type Listing = { section: string; path: string; revision: number; entries: Entry[]; total: number; offset: number; next_offset: number | null; legacy_cursor: string | null; notice: string | null; path_archived: boolean };
type Dialog = { kind: "folder" } | { kind: "rename" | "history"; entry: Entry };
type UploadTask = { name: string; state: "waiting" | "uploading" | "done" | "error" | "stopped"; progress: number; error?: string };
const btn = "gap-2 rounded-xl text-sm font-medium normal-case tracking-normal";
const field = "w-full rounded-xl border border-zinc-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-amber-500";

export function SalesFileLibrary({ section, path, canManage, onNavigate }: { section: "photos" | "catalogs"; path: string; canManage: boolean; onNavigate: (path: string) => void }) {
  const [data, setData] = useState<Listing | null>(null);
  const dataRef = useRef<Listing | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState(false);
  const [offset, setOffset] = useState(0);
  const [cursor, setCursor] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [preview, setPreview] = useState<Material | null>(null);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [name, setName] = useState("");
  const [versions, setVersions] = useState<AssetVersion[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [tasks, setTasks] = useState<UploadTask[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const replaceRef = useRef<HTMLInputElement>(null);
  const replacement = useRef<Entry | null>(null);
  const stopped = useRef(false);
  const alive = useRef(true);
  const running = useRef(false);
  const previewRef = useRef<HTMLDivElement>(null);
  const historyRequest = useRef<AbortController | null>(null);
  const dirty = dialog?.kind === "folder" ? !!name.trim() : dialog?.kind === "rename" && name !== dialog.entry.name;
  useLeaveGuard(!!busy || !!dirty, busy ? "Идёт загрузка или сохранение. Покинуть раздел? Уже отправленный файл может сохраниться, остальные не будут загружены." : "Покинуть раздел без сохранения изменений?", () => { stopped.current = true; }, () => { stopped.current = false; });
  useEffect(() => { alive.current = true; return () => { alive.current = false; stopped.current = true; historyRequest.current?.abort(); }; }, []);
  useEffect(() => { const timer = setTimeout(() => { setSearch(query.trim()); setOffset(0); }, 300); return () => clearTimeout(timer); }, [query]);
  useEffect(() => { setOffset(0); setCursor(null); setQuery(""); setPreview(null); setTasks([]); setDialog(null); }, [path]);
  const accept = useCallback((next: Listing) => { dataRef.current = next; setData(next); setPreview(current => current ? next.entries.find(entry => entry.asset?.asset_id === current.asset_id)?.asset || current : null); }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null);
    if (dataRef.current?.path !== path) { setData(null); dataRef.current = null; }
    const params = new URLSearchParams({ section, path, include_archived: String(archived && canManage), offset: String(offset), q: search });
    if (cursor) params.set("legacy_cursor", cursor);
    void apiFetch<Listing>(`/sales-files/list?${params}`, { signal: controller.signal }).then(next => { if (!controller.signal.aborted) accept(next); })
      .catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Не удалось загрузить файлы"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [section, path, search, archived, offset, cursor, refresh, canManage, accept]);

  function showPreview(asset: Material) { setPreview(asset); setTimeout(() => previewRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 30); }
  async function download(asset: Material) { try { await downloadMaterial(asset.asset_id); } catch (e) { setError(e instanceof Error ? e.message : "Не удалось скачать файл"); } }
  async function mutate(url: string, method: string, payload: object): Promise<boolean> {
    if (!dataRef.current || running.current) return false;
    running.current = true; setBusy(true); setError(null);
    try {
      const next = await apiFetch<Listing>(url, { method, body: JSON.stringify({ ...payload, revision: dataRef.current.revision }) });
      if (alive.current) { accept(next); setOffset(0); setQuery(""); setPreview(null); setRefresh(n => n + 1); }
      return true;
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : "Изменения не сохранены"); return false; }
    finally { running.current = false; if (alive.current) setBusy(false); }
  }
  function archive(entry: Entry) {
    if (!window.confirm(entry.is_archived ? `Восстановить «${entry.name}»?` : entry.kind === "folder" ? `Убрать «${entry.name}» со всем содержимым в архив? Данные в хранилище не удаляются.` : `Убрать «${entry.name}» в архив? Все версии можно восстановить.`)) return;
    void mutate(`/sales-files/entries/${entry.id}`, "PATCH", { is_archived: !entry.is_archived });
  }
  async function upload(files: FileList | File[], replace?: Entry) {
    if (!files.length || !dataRef.current || running.current) return;
    if (!replace && files.length > 50) { setError("За один раз можно добавить до 50 файлов. Разделите загрузку на несколько частей; ни один файл ещё не отправлен."); return; }
    const queue = Array.from(files).slice(0, replace ? 1 : 50);
    let failed = false;
    running.current = true; stopped.current = false; setBusy(true); setError(null);
    setTasks(queue.map(f => ({ name: f.name, state: "waiting", progress: 0 })));
    const update = (index: number, values: Partial<UploadTask>) => { if (alive.current) setTasks(list => list.map((item, i) => i === index ? { ...item, ...values } : item)); };
    try {
      for (let index = 0; index < queue.length; index++) {
        if (stopped.current || !alive.current) { for (let j = index; j < queue.length; j++) update(j, { state: "stopped" }); break; }
        const file = queue[index];
        if (!file.size || file.size > 512 * 1024 * 1024) { update(index, { state: "error", error: "Нужен непустой файл до 512 МБ" }); continue; }
        const form = new FormData(); form.append("file", file); form.append("section", section); form.append("path", path);
        form.append("revision", String(dataRef.current!.revision)); if (replace) form.append("replace_id", replace.id);
        update(index, { state: "uploading" });
        try {
          const next = await uploadMaterial<Listing>("/sales-files/upload", form, progress => update(index, { progress }));
          if (alive.current) { accept(next); setOffset(0); setQuery(""); }
          update(index, { state: "done", progress: 100 });
        } catch (e) {
          failed = true;
          update(index, { state: "error", error: e instanceof Error ? e.message : "Загрузка не подтверждена" });
          if (alive.current) setError("Очередь остановлена. Обновите список и проверьте, сохранился ли последний файл, перед повторной загрузкой.");
          for (let j = index + 1; j < queue.length; j++) update(j, { state: "stopped" });
          break;
        }
      }
    } finally { running.current = false; if (alive.current) { setBusy(false); if (!failed) setRefresh(n => n + 1); } }
  }
  async function openHistory(entry: Entry) {
    historyRequest.current?.abort(); const controller = new AbortController(); historyRequest.current = controller;
    setDialog({ kind: "history", entry }); setVersions([]); setHistoryLoading(true); setError(null);
    try {
      const result = await apiFetch<{ items: AssetVersion[] }>(`/sales-files/entries/${entry.id}/versions`, { signal: controller.signal });
      if (!controller.signal.aborted) setVersions(result.items);
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Не удалось получить версии"); }
    finally { if (!controller.signal.aborted) setHistoryLoading(false); }
  }
  function closeDialog() { if (!busy && (!dirty || window.confirm("Закрыть без сохранения изменений?"))) { historyRequest.current?.abort(); setDialog(null); } }
  async function saveDialog() {
    if (!dialog || !name.trim()) return;
    const ok = dialog.kind === "folder" ? await mutate("/sales-files/mkdir", "POST", { section, path, name: name.trim() }) : dialog.kind === "rename" ? await mutate(`/sales-files/entries/${dialog.entry.id}`, "PATCH", { name: name.trim() }) : false;
    if (ok) setDialog(null);
  }
  const entries = data?.entries.filter(e => archived || !e.is_archived) || [];
  const canWrite = canManage && !busy && !loading && !!data && !data.path_archived;

  return <div className="space-y-5">
    <section className="min-w-0 rounded-2xl border border-zinc-200 bg-white p-4 sm:p-6">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3"><nav aria-label="Папки продаж" className="flex min-w-0 flex-wrap items-center gap-1.5 text-sm text-zinc-500"><button type="button" disabled={busy} onClick={() => onNavigate("")} className="rounded-lg px-2 py-1.5 font-medium text-zinc-800 hover:bg-zinc-50">{section === "photos" ? "Фото" : "Каталоги"}</button>{path.split("/").filter(Boolean).map((part, index, parts) => <span key={index} className="flex min-w-0 items-center gap-1.5"><ChevronRight size={13} className="shrink-0" /><button type="button" disabled={busy} className="max-w-[260px] truncate rounded-lg px-1.5 py-1.5 hover:bg-zinc-50" onClick={() => onNavigate(parts.slice(0, index + 1).join("/"))}>{part}</button></span>)}</nav><Button variant="ghost" size="sm" className={btn} disabled={busy || loading} onClick={() => { setCursor(null); setRefresh(n => n + 1); }}><RefreshCw size={15} />Обновить список</Button></div>
      {error && !dialog && <p role="alert" className="mb-4 rounded-xl bg-rose-50 p-4 text-sm leading-6 text-rose-800">{error}</p>}
      {data?.notice && <p role="status" className="mb-4 rounded-xl bg-amber-50 p-4 text-xs leading-6 text-amber-900">{data.notice}</p>}
      {data?.path_archived && <p className="mb-4 rounded-xl bg-amber-50 p-4 text-sm text-amber-900">Папка находится в архиве. Для загрузки и восстановления файлов сначала восстановите родительскую папку.</p>}
      <div className="mb-4 flex flex-wrap items-center gap-3"><label className="flex min-w-0 flex-[1_1_240px] items-center gap-2 rounded-xl border border-zinc-200 px-3 text-zinc-400"><Search size={16} /><input aria-label="Поиск файлов продаж" maxLength={200} className="h-11 w-full min-w-0 bg-transparent text-sm text-zinc-800 outline-none" value={query} onChange={e => setQuery(e.target.value)} placeholder="Поиск в этой папке…" disabled={busy} /></label>{canManage && <label className="flex items-center gap-2 text-xs text-zinc-500"><input type="checkbox" checked={archived} onChange={e => { setArchived(e.target.checked); setOffset(0); }} disabled={busy} className="h-4 w-4 accent-amber-600" />Показывать архив</label>}</div>
      {canManage && <div className={cn("mb-5 rounded-xl border border-dashed p-4 text-sm", dragging ? "border-amber-500 bg-amber-50" : "border-zinc-300 bg-zinc-50/50")} onDragOver={e => { e.preventDefault(); if (canWrite) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); if (canWrite) void upload(e.dataTransfer.files); }}><div className="flex flex-wrap items-center justify-between gap-3"><p className="flex items-center gap-2 text-xs leading-6 text-zinc-500"><UploadCloud size={20} className="shrink-0" />Перетащите до 50 файлов · до 512 МБ каждый</p><div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" className={btn} disabled={!canWrite} onClick={() => { setName(""); setDialog({ kind: "folder" }); }}><FolderPlus size={15} />Новая папка</Button><Button size="sm" className={btn} disabled={!canWrite} onClick={() => inputRef.current?.click()}><UploadCloud size={15} />Добавить файлы</Button></div></div><input ref={inputRef} type="file" multiple className="sr-only" aria-label="Добавить файлы продаж" disabled={!canWrite} onChange={e => { if (e.target.files) void upload(e.target.files); e.target.value = ""; }} /><input ref={replaceRef} type="file" className="sr-only" aria-label="Заменить файл продаж" disabled={!canWrite} onChange={e => { const entry = replacement.current; if (entry && e.target.files) void upload(e.target.files, entry); e.target.value = ""; replacement.current = null; }} /></div>}
      {tasks.length > 0 && <div aria-label="Загрузки продаж" className="mb-5 space-y-2 rounded-xl border border-zinc-200 p-4">{tasks.map((task, index) => <div key={index} className="text-xs leading-6"><div className="flex items-start justify-between gap-3"><span className="min-w-0 break-words">{task.name}</span><span className={cn("shrink-0", task.state === "error" ? "text-rose-700" : task.state === "done" ? "text-emerald-700" : "text-zinc-400")}>{task.state === "done" ? "Сохранён" : task.state === "uploading" ? `${task.progress}%` : task.state === "error" ? "Ошибка" : task.state === "stopped" ? "Не отправлен" : "В очереди"}</span></div>{task.state === "uploading" && <div className="mt-1 h-1 overflow-hidden rounded-full bg-zinc-100"><div className="h-full bg-amber-500" style={{ width: `${task.progress}%` }} /></div>}{task.error && <p className="text-rose-700">{task.error}</p>}</div>)}{busy && <button type="button" onClick={() => { stopped.current = true; }} className="mt-2 text-xs font-medium text-amber-800 underline">Остановить после текущего файла</button>}</div>}
      {path && <button type="button" disabled={busy} onClick={() => onNavigate(path.split("/").slice(0, -1).join("/"))} className="mb-3 flex items-center gap-2 rounded-lg py-2 text-xs font-medium text-zinc-500"><ArrowLeft size={14} />На уровень выше</button>}
      {loading && <p role="status" className="flex items-center justify-center gap-2 py-8 text-sm text-zinc-500"><Loader2 size={18} className="animate-spin" />Обновляем файлы…</p>}
      {!loading && !entries.length && <p className="py-12 text-center text-sm leading-7 text-zinc-500">{search ? "По этому запросу файлов нет." : "В папке пока нет материалов."}{canWrite && !search && <span className="block text-xs">Добавьте файлы или создайте папку — оригиналы будут сохранены в S3.</span>}</p>}
      {!loading && entries.length > 0 && <div className="divide-y divide-zinc-100 rounded-xl border border-zinc-200">{entries.map(entry => <div key={entry.id} className={cn("flex min-w-0 flex-wrap items-center gap-2 px-3 py-3 sm:px-4", entry.is_archived && "bg-zinc-50")}>
        <button type="button" disabled={busy} onClick={() => entry.kind === "folder" ? onNavigate(entry.path) : entry.asset && showPreview(entry.asset)} className="flex min-w-0 flex-[1_1_160px] items-center gap-3 text-left"><span className={cn("shrink-0 rounded-xl p-2.5", entry.kind === "folder" ? "bg-amber-50 text-amber-700" : "bg-zinc-50 text-zinc-400")}>{entry.kind === "folder" ? <Folder size={20} /> : <MaterialIcon name={entry.name} />}</span><span className="min-w-0"><span className="block break-words text-sm font-medium text-zinc-800">{entry.name}</span><span className="mt-1 block text-[11px] text-zinc-400">{entry.kind === "folder" ? "Папка" : `${formatBytes(entry.asset?.size_bytes)} · v${entry.asset?.version || 1}`}{entry.is_archived ? " · В архиве" : ""}</span></span></button>
        <div className="ml-auto flex shrink-0 items-center gap-1">{entry.asset && <button type="button" title="Скачать оригинал" aria-label={`Скачать ${entry.name}`} onClick={() => void download(entry.asset!)} className="rounded-lg p-2 text-zinc-400 hover:bg-zinc-50 hover:text-zinc-800"><Download size={17} /></button>}{canManage && (entry.is_archived ? <Button variant="ghost" size="sm" className={btn} disabled={busy || data?.path_archived} onClick={() => archive(entry)}><RotateCcw size={15} />Восстановить</Button> : <details className="relative"><summary aria-label={`Действия с ${entry.name}`} className="flex cursor-pointer list-none rounded-lg p-2 text-zinc-400 hover:bg-zinc-100 [&::-webkit-details-marker]:hidden"><MoreHorizontal size={19} /></summary><div className="absolute right-0 z-20 mt-1 w-52 rounded-xl border border-zinc-200 bg-white p-1.5 shadow-lg" onClick={e => e.currentTarget.closest("details")?.removeAttribute("open")}>{entry.kind === "file" && <><button type="button" disabled={!canWrite} className="flex w-full items-center gap-2 rounded-lg p-2.5 text-left text-xs hover:bg-zinc-50" onClick={() => { replacement.current = entry; replaceRef.current?.click(); }}><UploadCloud size={14} />Заменить файл</button><button type="button" disabled={!canWrite} className="flex w-full items-center gap-2 rounded-lg p-2.5 text-left text-xs hover:bg-zinc-50" onClick={() => { setName(entry.name); setDialog({ kind: "rename", entry }); }}><Pencil size={14} />Переименовать</button><button type="button" disabled={busy} className="flex w-full items-center gap-2 rounded-lg p-2.5 text-left text-xs hover:bg-zinc-50" onClick={() => void openHistory(entry)}><History size={14} />История версий</button></>}<button type="button" disabled={busy} className="flex w-full items-center gap-2 rounded-lg p-2.5 text-left text-xs text-rose-700 hover:bg-rose-50" onClick={() => archive(entry)}><Archive size={14} />Переместить в архив</button></div></details>)}</div>
      </div>)}</div>}
      {data && <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-zinc-400"><span>Записей в папке: {data.total}</span><div className="flex items-center gap-3">{offset > 0 && <button type="button" disabled={busy || loading} onClick={() => setOffset(n => Math.max(0, n - 100))} className="text-zinc-600 underline">Предыдущие</button>}{data.next_offset != null && <button type="button" disabled={busy || loading} onClick={() => setOffset(data.next_offset!)} className="text-zinc-600 underline">Следующие</button>}{data.legacy_cursor && <button type="button" disabled={busy || loading} onClick={() => { setCursor(data.legacy_cursor); setOffset(0); }} className="text-amber-800 underline">Загрузить ещё из хранилища</button>}</div></div>}
    </section>
    {preview && <div ref={previewRef} className="scroll-mt-24"><AssetPreview asset={preview} onClose={() => setPreview(null)} /></div>}
    <p className="flex items-start gap-2 px-1 text-xs leading-6 text-zinc-500"><ShieldCheck size={16} className="mt-1 shrink-0 text-emerald-700" />Файлы хранятся отдельно от Google Sheets. Замена создаёт новую версию, архив скрывает материал без удаления оригиналов. Видео готовится для браузера в фоне.</p>
    <Modal open={!!dialog} title={dialog?.kind === "history" ? "История файла" : dialog?.kind === "rename" ? "Переименовать файл" : "Новая папка"} onClose={closeDialog} disableClose={busy} className="max-w-xl" footer={dialog?.kind === "history" ? <Button variant="outline" className={btn} onClick={closeDialog}>Закрыть</Button> : <div className="flex justify-end gap-2"><Button variant="ghost" className={btn} disabled={busy} onClick={closeDialog}>Отмена</Button><Button className={btn} disabled={busy || !name.trim()} onClick={() => void saveDialog()}>{busy && <Loader2 size={16} className="animate-spin" />}Сохранить</Button></div>}>
      {error && <p role="alert" className="mb-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
      {dialog?.kind !== "history" ? <label className="block space-y-2 text-sm font-medium">Название<input autoFocus className={field} value={name} maxLength={400} onChange={e => setName(e.target.value)} disabled={busy} /></label> : <div className="space-y-3">
  <p className="break-words text-sm font-medium">{dialog.entry.name}</p>
  <AssetVersionList
    versions={versions}
    loading={historyLoading}
    current={<p className="text-xs text-zinc-500">Текущая версия: {dialog.entry.asset?.version}. Восстановление не удалит другие версии.</p>}
    empty="Этот файл ещё не заменяли."
    disabled={busy}
    onRestore={version => {
      if (window.confirm(`Восстановить версию ${version.version}? Текущая останется в истории.`)) {
        void mutate(`/sales-files/entries/${dialog.entry!.id}/restore-version`, "POST", { version: version.version }).then(ok => { if (ok) setDialog(null); });
      }
    }}
  />
</div>}
    </Modal>
  </div>;
}
