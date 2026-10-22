"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ModuleQuizEditor } from "./module-quiz-editor";
import type { EditorAsset, EditorLesson, Workspace } from "./editor-types";
import { useCallback, useEffect, useRef, useState } from "react";
import { Archive, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, BookOpen, Check, CheckCircle2, ChevronRight, Download, Eye, FilePlus2, Folder, GraduationCap, History, Info, Loader2, MoreHorizontal, Pencil, Plus, RefreshCw, RotateCcw, Save, Search, Settings2, ShieldCheck, UploadCloud, X } from "lucide-react";
import { LessonPresentation } from "@/components/learning/lesson-presentation";
import { AppShell } from "@/components/app/shell";
import { AssetPreview } from "@/components/materials/asset-preview";
import { MaterialIcon } from "@/components/materials/material-browser";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { useActiveTabVisibility } from "@/lib/hooks/use-active-tab-visibility";
import { useLeaveGuard } from "@/lib/hooks/use-leave-guard";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useAuth } from "@/lib/hooks/use-auth";
import { downloadMaterial, fileExtension, formatBytes, formatFileCount, uploadMaterial, type Material } from "@/lib/materials";

type Tab = "materials" | "tests" | "settings" | "import" | "archive";
type FileTask = { name: string; percent: number; state: "waiting" | "uploading" | "done" | "error" | "stopped"; error?: string };
type ImportReport = { lessons_added?: number; lessons_updated?: number; lessons_kept?: number; files_added?: number; files_updated?: number; files_unchanged?: number; warnings?: string[] };
type Job = { id: string; status: string; stage?: string; detail?: string; error_message?: string; error_hint?: string; result?: { ok: boolean; canceled?: boolean; report?: ImportReport } };
type Dialog =
  | { kind: "lesson"; lesson?: EditorLesson; folder: boolean; revision: number }
  | { kind: "rename"; asset: EditorAsset }
  | { kind: "move"; asset: EditorAsset }
  | { kind: "versions"; asset: EditorAsset }
  | { kind: "textVersions"; lesson: EditorLesson; revision: number }
  | { kind: "confirm"; title: string; description: string; action: () => Promise<boolean> };
const btn = "gap-2 rounded-xl text-sm font-medium normal-case tracking-normal";
const input = "w-full rounded-xl border border-zinc-200 bg-white px-3.5 py-2.5 text-sm text-zinc-900 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-100 disabled:bg-zinc-50";

export function ModuleEditor({ moduleId }: { moduleId: string }) {
  const params = useSearchParams();
  const { user, loading: authLoading } = useAuth();
  const [data, setData] = useState<Workspace | null>(null);
  const dataRef = useRef<Workspace | null>(null);
  const settingsDirtyRef = useRef(false);
  const settingsRevisionRef = useRef(1);
  const versionRequest = useRef<AbortController | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>(params.get("tab") === "tests" ? "tests" : params.get("tab") === "settings" ? "settings" : "materials");
  const tabsRef = useActiveTabVisibility(tab);
  const [selected, setSelected] = useState<string | null>(params.get("lesson"));
  const [quizDirty, setQuizDirty] = useState(false);
  const [quizReset, setQuizReset] = useState(0);
  const quizWorking = useCallback((working: boolean) => setBusy(working ? "quiz" : null), []);
  const [query, setQuery] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [draftMode, setDraftMode] = useState<"manual" | "import">("manual");
  const [textVersions, setTextVersions] = useState<{ version: number; created_at: string; content_mode: string }[]>([]);
  const [textPreview, setTextPreview] = useState<{ version: number; content: string } | null>(null);
  const [textLoading, setTextLoading] = useState(false);
  const [draftOutline, setDraftOutline] = useState("");
  const [draftPresentation, setDraftPresentation] = useState<"auto" | "material" | "text">("auto");
  const [draftPrimary, setDraftPrimary] = useState("");
  const [tags, setTags] = useState<{ id: string; name: string }[]>([]);
  const [tagsError, setTagsError] = useState<string | null>(null);
  const [draftTarget, setDraftTarget] = useState("");
  const [showMarkdown, setShowMarkdown] = useState(false);
  const [moduleDraft, setModuleDraft] = useState({ title: "", description: "", category: "", visibility: "public", tag_ids: [] as string[] });
  const [versions, setVersions] = useState<{ version: number; filename: string; size_bytes: number | null; created_at: string }[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [tasks, setTasks] = useState<FileTask[]>([]);
  const [dragging, setDragging] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPercent, setImportPercent] = useState(0);
  const [job, setJob] = useState<Job | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const uploadInput = useRef<HTMLInputElement>(null);
  const replaceInput = useRef<HTMLInputElement>(null);
  const replacement = useRef<EditorAsset | null>(null);
  const stopQueue = useRef(false);
  const uploadRunning = useRef(false);
  const previewRef = useRef<HTMLDivElement>(null);
  const base = `/admin/content/modules/${moduleId}`;
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";
  const moduleMeta = data?.module;
  const selectedLesson = data?.lessons.find(l => l.id === selected) || null;
  const activeLessons = data?.lessons.filter(l => !l.is_archived) || [];
  const preview = data?.assets.find(a => a.asset_id === previewId) || null;
  const archivedLessons = data?.lessons.filter(l => l.is_archived) || [];
  const archiveCount = archivedLessons.length + (data?.assets.filter(a => a.is_archived).length || 0);
  const files = (data?.assets || []).filter(a => tab === "archive" ? a.is_archived : !a.is_archived && a.submodule_id === selected)
    .filter(a => a.original_filename.toLocaleLowerCase("ru").includes(query.trim().toLocaleLowerCase("ru")));
  const settingsDirty = !!moduleMeta && (moduleDraft.title !== moduleMeta.title || moduleDraft.description !== (moduleMeta.description || "") || moduleDraft.category !== (moduleMeta.category || "") || moduleDraft.visibility !== moduleMeta.visibility || JSON.stringify([...moduleDraft.tag_ids].sort()) !== JSON.stringify([...(moduleMeta.tag_ids || [])].sort()));
  const editingDirty = dialog?.kind === "lesson" && (draftTitle !== (dialog.lesson?.title || "") || draftContent !== (dialog.lesson?.content || "") || draftOutline !== (dialog.lesson?.outline_path || "") || draftPresentation !== (dialog.lesson?.presentation_mode || "auto") || draftPrimary !== (dialog.lesson?.primary_asset_id || "") || draftMode !== (dialog.lesson?.content_mode || "manual"));
  const dirty = quizDirty || settingsDirty || editingDirty || (dialog?.kind === "rename" && draftTitle !== dialog.asset.original_filename.split("/").at(-1)) || (dialog?.kind === "move" && draftTarget !== (dialog.asset.submodule_id || ""));
  settingsDirtyRef.current = settingsDirty;
  const locked = !!busy || !!moduleMeta?.is_archived;
  const jobRunning = !!jobId && !["finished", "failed", "canceled", "stopped", "missing"].includes(job?.status || "queued");

  const accept = useCallback((next: Workspace) => {
    if (dataRef.current?.module.id === next.module.id && dataRef.current.module.content_revision > next.module.content_revision) return;
    dataRef.current = next;
    setData(next);
    setConflict(false);
  }, []);
  const resetDraft = (next: Workspace) => {
    settingsRevisionRef.current = next.module.content_revision;
    settingsDirtyRef.current = false;
    setModuleDraft({ title: next.module.title, description: next.module.description || "", category: next.module.category || "", visibility: next.module.visibility, tag_ids: next.module.tag_ids || [] });
  };
  const load = useCallback(async (discard = false, signal?: AbortSignal) => {
    try {
      setError(null);
      const next = await apiFetch<Workspace>(base, { signal });
      if (signal?.aborted || (dataRef.current?.module.id === next.module.id && dataRef.current.module.content_revision > next.module.content_revision)) return;
      const keepDraft = settingsDirtyRef.current && !discard;
      accept(next);
      if (discard) setQuizReset(n => n + 1);
      if (!keepDraft) resetDraft(next);
      else setConflict(true);
    } catch (e) { if (!signal?.aborted) setError(e instanceof Error ? e.message : "Не удалось загрузить модуль"); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [base, accept]);

  useEffect(() => {
    const controller = new AbortController();
    if (isAdmin) void load(false, controller.signal); else if (!authLoading) setLoading(false);
    return () => controller.abort();
  }, [isAdmin, authLoading, load]);
  useEffect(() => {
    if (!isAdmin || tab !== "settings") return;
    const controller = new AbortController();
    setTagsError(null);
    void apiFetch<{ items: { id: string; name: string }[] }>("/admin/tags", { signal: controller.signal }).then(result => { if (!controller.signal.aborted) setTags(result.items); }).catch(e => { if (!controller.signal.aborted) setTagsError(e instanceof Error ? e.message : "Не удалось загрузить теги"); });
    return () => controller.abort();
  }, [isAdmin, tab]);
  useEffect(() => () => { versionRequest.current?.abort(); stopQueue.current = true; }, []);
  useLeaveGuard(!!dirty || !!busy,
    busy ? "Идёт сохранение или загрузка. Покинуть редактор? Оставшиеся файлы в очереди не будут отправлены." : "Есть несохранённые изменения. Покинуть редактор без сохранения?",
    () => { stopQueue.current = true; }, () => { stopQueue.current = false; });

  useEffect(() => { setChecked(new Set()); setQuery(""); setPreviewId(null); }, [selected, tab]);
  useEffect(() => {
    try { const id = sessionStorage.getItem(`corelms:update-job:${moduleId}`); if (id) setJobId(id); } catch { /* storage may be disabled */ }
  }, [moduleId]);

  useEffect(() => {
    if (!jobId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await apiFetch<Job>(`/admin/jobs/${encodeURIComponent(jobId)}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setJob(next);
        if (["finished", "failed", "canceled", "stopped", "missing"].includes(next.status)) {
          if (next.status === "finished" && next.result?.ok) await load();
          return;
        }
      } catch (e) {
        if (controller.signal.aborted) return;
        setJob(previous => ({ ...(previous || { id: jobId, status: "queued" }), error_message: "Не удалось получить статус. Проверяем соединение…" }));
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 2500);
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [jobId, load]);

  async function mutate(path: string, method: string, payload: Record<string, unknown>, message = "Изменения сохранены", expectedRevision?: number): Promise<boolean> {
    if (!dataRef.current || busy) return false;
    setBusy("save"); setError(null);
    try {
      const next = await apiFetch<Workspace>(`${base}${path}`, { method, body: JSON.stringify({ ...payload, revision: expectedRevision ?? (path === "" && settingsDirty ? settingsRevisionRef.current : dataRef.current.module.content_revision) }) });
      accept(next);
      if (!settingsDirty || path === "") resetDraft(next);
      window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: message, description: "История обучения сохранена" } }));
      return true;
    } catch (e) {
      if ((e as { status?: number }).status === 409) setConflict(true);
      setError(e instanceof Error ? e.message : "Не удалось сохранить изменения");
      return false;
    } finally { setBusy(null); }
  }

  function changeTab(next: Tab) {
    if ((settingsDirty || quizDirty) && !window.confirm("Есть несохранённые изменения. Перейти без сохранения?")) return;
    if (data) resetDraft(data);
    setTab(next);
  }
  async function openLesson(lesson?: EditorLesson, folder = false) {
    let resolved = lesson;
    let revision = dataRef.current?.module.content_revision || 1;
    if (lesson?.has_external_content) {
      setBusy("Текст урока"); setError(null);
      try {
        const result = await apiFetch<{ content: string; content_version: number; revision: number }>(`${base}/lessons/${lesson.id}/content`);
        if (result.revision !== revision) throw new Error("Модуль изменён в другой вкладке. Нажмите «Обновить данные модуля» и откройте урок снова — так чужие изменения не будут перезаписаны.");
        resolved = { ...lesson, content: result.content, content_version: result.content_version };
      } catch (err) { setError(err instanceof Error ? err.message : "Не удалось загрузить текст"); return; }
      finally { setBusy(null); }
    }
    setDraftTitle(resolved?.title || ""); setDraftContent(resolved?.content || ""); setDraftMode(resolved?.content_mode || "manual");
    setDraftOutline(resolved?.outline_path || ""); setDraftPresentation(resolved?.presentation_mode || "auto"); setDraftPrimary(dataRef.current?.assets.some(a => !a.is_archived && a.submodule_id === resolved?.id && a.asset_id === resolved?.primary_asset_id) ? resolved?.primary_asset_id || "" : ""); setShowMarkdown(false);
    setError(null); setDialog({ kind: "lesson", lesson: resolved, folder: resolved?.is_folder ?? folder, revision });
  }
  async function openTextHistory(lesson: EditorLesson) {
    versionRequest.current?.abort(); const controller = new AbortController(); versionRequest.current = controller;
    setError(null); setTextVersions([]); setTextPreview(null); setVersionsLoading(true); setTextLoading(false);
    setDialog({ kind: "textVersions", lesson, revision: dataRef.current?.module.content_revision || 1 });
    try {
      const result = await apiFetch<{ items: typeof textVersions }>(`${base}/lessons/${lesson.id}/versions`, { signal: controller.signal });
      if (!controller.signal.aborted) setTextVersions(result.items);
    } catch (err) { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Не удалось загрузить историю"); }
    finally { if (!controller.signal.aborted) setVersionsLoading(false); }
  }
  async function previewTextVersion(lesson: EditorLesson, version: number) {
    versionRequest.current?.abort(); const controller = new AbortController(); versionRequest.current = controller;
    setTextLoading(true); setTextPreview(null); setError(null);
    try {
      const result = await apiFetch<{ version: number; content: string }>(`${base}/lessons/${lesson.id}/versions/${version}`, { signal: controller.signal });
      if (!controller.signal.aborted) setTextPreview(result);
    } catch (err) { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Не удалось загрузить версию"); }
    finally { if (!controller.signal.aborted) setTextLoading(false); }
  }
  function closeDialog() {
    if (busy) return;
    if ((editingDirty || (dialog?.kind === "rename" && draftTitle !== dialog.asset.original_filename.split("/").at(-1)) || (dialog?.kind === "move" && draftTarget !== (dialog.asset.submodule_id || ""))) && !window.confirm("Закрыть без сохранения изменений?")) return;
    versionRequest.current?.abort();
    setDialog(null);
  }
  async function saveDialog() {
    if (!dialog) return;
    let saved = false;
    if (dialog.kind === "lesson") {
      if (!draftTitle.trim()) { setError("Введите название"); return; }
      saved = await mutate(dialog.lesson ? `/lessons/${dialog.lesson.id}` : "/lessons", dialog.lesson ? "PATCH" : "POST", {
        title: draftTitle.trim(), ...(!dialog.lesson || draftContent !== dialog.lesson.content ? { content: draftContent } : {}), outline_path: draftOutline.trim() || null,
        presentation_mode: draftPresentation,
        ...(dialog.lesson ? { primary_asset_id: draftPrimary || null, content_mode: draftMode } : { is_folder: dialog.folder }),
      }, dialog.lesson ? "Урок обновлён" : "Материал создан", dialog.revision);
      if (saved && !dialog.lesson) setSelected(dataRef.current?.lessons.at(-1)?.id || null);
    } else if (dialog.kind === "rename") saved = await mutate(`/assets/${dialog.asset.asset_id}`, "PATCH", { filename: draftTitle.trim() }, "Файл переименован");
    else if (dialog.kind === "move") saved = await mutate(`/assets/${dialog.asset.asset_id}`, "PATCH", { submodule_id: draftTarget || null }, "Файл перемещён");
    else if (dialog.kind === "confirm") saved = await dialog.action();
    if (saved) { setDialog(null); setChecked(new Set()); }
  }
  function archiveLesson(lesson: EditorLesson) {
    setDialog({ kind: "confirm", title: "Переместить в архив?", description: `«${lesson.title}» и его файлы станут недоступны ученикам. Прочтения, тесты и результаты сохранятся. Материал можно восстановить.`, action: async () => {
      const ok = await mutate(`/lessons/${lesson.id}`, "PATCH", { is_archived: true }, "Материал в архиве");
      if (ok && selected === lesson.id) setSelected(null);
      return ok;
    } });
  }
  function archiveFiles(ids: string[]) {
    setDialog({ kind: "confirm", title: ids.length === 1 ? "Убрать файл из обучения?" : `Убрать ${ids.length} файлов?`, description: "Файлы попадут в архив этого модуля. Их можно вернуть вместе с версиями; результаты учеников не изменятся.", action: () => mutate("/assets/archive", "POST", { ids, is_archived: true }, "Файлы перемещены в архив") });
  }
  async function reorder(lesson: EditorLesson, direction: -1 | 1) {
    const ids = activeLessons.map(l => l.id); const index = ids.indexOf(lesson.id); const target = index + direction;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    await mutate("/lesson-order", "PUT", { ids }, "Порядок уроков изменён");
  }
  async function reorderFile(asset: EditorAsset, direction: -1 | 1) {
    const ids = (data?.assets || []).filter(a => !a.is_archived && a.submodule_id === selected).map(a => a.asset_id);
    const index = ids.indexOf(asset.asset_id), target = index + direction;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    await mutate("/asset-order", "PUT", { ids, submodule_id: selected }, "Порядок файлов изменён");
  }

  async function upload(filesToUpload: File[], replace?: EditorAsset) {
    if (!filesToUpload.length || uploadRunning.current || locked || !dataRef.current) return;
    if (filesToUpload.length > 100) { setError("За один раз можно добавить до 100 файлов."); return; }
    uploadRunning.current = true; stopQueue.current = false; setBusy("upload"); setError(null);
    setTasks(filesToUpload.map(f => ({ name: f.name, percent: 0, state: "waiting" })));
    let index = 0;
    for (const file of filesToUpload) {
      if (stopQueue.current) break;
      const position = index;
      setTasks(prev => prev.map((t, i) => i === position ? { ...t, state: "uploading" } : t));
      const form = new FormData();
      form.append("file", file); form.append("revision", String(dataRef.current.module.content_revision));
      if (replace) form.append("replace_asset_id", replace.asset_id);
      else if (selected) form.append("submodule_id", selected);
      try {
        const next = await uploadMaterial<Workspace>(`${base}/assets`, form, percent => setTasks(prev => prev.map((t, i) => i === position ? { ...t, percent } : t)));
        accept(next);
        setTasks(prev => prev.map((t, i) => i === position ? { ...t, percent: 100, state: "done" } : t));
      } catch (e) {
        const message = e instanceof Error ? e.message : "Не удалось загрузить файл";
        setTasks(prev => prev.map((t, i) => i === position ? { ...t, state: "error", error: message } : t));
        setError(message);
        break; // Don't continue with a possibly stale revision after a network failure.
      }
      index += 1;
    }
    setTasks(prev => prev.map(t => t.state === "waiting" ? { ...t, state: "stopped" } : t));
    uploadRunning.current = false; setBusy(null);
  }

  async function showVersions(asset: EditorAsset) {
    versionRequest.current?.abort();
    const controller = new AbortController();
    versionRequest.current = controller;
    setError(null); setVersions([]); setVersionsLoading(true); setDialog({ kind: "versions", asset });
    try {
      const result = await apiFetch<{ items: typeof versions }>(`${base}/assets/${asset.asset_id}/versions`, { signal: controller.signal });
      if (!controller.signal.aborted) setVersions(result.items);
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Не удалось загрузить версии"); }
    finally { if (!controller.signal.aborted) setVersionsLoading(false); }
  }
  function openPreview(asset: Material) { setPreviewId(asset.asset_id); setTimeout(() => previewRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 40); }
  async function download(asset: Material) {
    try { await downloadMaterial(asset.asset_id); }
    catch (e) { setError(e instanceof Error ? e.message : "Не удалось скачать файл"); }
  }
  async function startReimport() {
    if (!importFile || !dataRef.current || busy || jobRunning) return;
    setBusy("import-upload"); setImportPercent(0); setError(null); setJob(null);
    const form = new FormData(); form.append("file", importFile); form.append("revision", String(dataRef.current.module.content_revision));
    try {
      const result = await uploadMaterial<{ job_id: string }>(`${base}/reimport`, form, setImportPercent);
      setJobId(result.job_id); setJob({ id: result.job_id, status: "queued" });
      try { sessionStorage.setItem(`corelms:update-job:${moduleId}`, result.job_id); } catch { /* optional persistence */ }
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось запустить импорт"); }
    finally { setBusy(null); }
  }

  const dialogTitle = dialog?.kind === "lesson" ? dialog.lesson ? "Редактирование материала" : dialog.folder ? "Новый каталог файлов" : "Новый урок" : dialog?.kind === "rename" ? "Переименовать файл" : dialog?.kind === "move" ? "Переместить файл" : dialog?.kind === "versions" ? "История версий" : dialog?.kind === "textVersions" ? "История текста урока" : dialog?.kind === "confirm" ? dialog.title : "";

  return <AppShell><div className="mx-auto w-full max-w-[1440px] px-4 py-7 sm:px-6 lg:py-10">
    <Link href="/admin/modules" className="mb-6 inline-flex items-center gap-2 text-sm text-zinc-500 hover:text-zinc-900"><ArrowLeft size={16} />Все модули</Link>
    {loading || authLoading ? <div role="status" className="flex min-h-80 items-center justify-center gap-3 text-zinc-500"><Loader2 className="animate-spin" />Загружаем редактор…</div> : !isAdmin ? <p role="alert">Редактор доступен только администраторам.</p> : !data || !moduleMeta ? <div role="alert" className="rounded-2xl border border-zinc-200 bg-white p-8"><h1 className="text-xl font-semibold">Не удалось открыть модуль</h1><p className="my-3 text-sm text-zinc-500">{error}</p><Button onClick={() => { if (!dirty || window.confirm("Обновить данные? Несохранённый черновик будет заменён данными сервера.")) { setDialog(null); void load(true); } }} className={btn}>Повторить</Button></div> : <>
      <header className="flex flex-wrap items-start justify-between gap-5">
        <div className="max-w-3xl"><div className="mb-2 flex items-center gap-3"><span className="text-xs font-semibold uppercase tracking-[0.16em] text-amber-700">Редактор модуля</span><span className={cn("rounded-full px-2.5 py-1 text-[11px] font-medium", moduleMeta.is_archived ? "bg-zinc-200 text-zinc-600" : moduleMeta.is_active ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800")}>{moduleMeta.is_archived ? "В архиве" : moduleMeta.is_active ? "Опубликован" : "Черновик"}</span></div><h1 className="break-words text-2xl font-semibold leading-tight tracking-tight text-zinc-950 sm:text-3xl">{moduleMeta.title}</h1><p className="mt-2 text-xs text-zinc-500">Редакция {moduleMeta.content_revision} · Изменения материалов не сбрасывают результаты обучения</p></div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="icon" aria-label="Обновить данные модуля" title="Обновить данные" disabled={!!busy} onClick={() => { if (!dirty || window.confirm("Обновить данные без сохранения черновика?")) { setDialog(null); void load(true); } }} className="rounded-xl"><RefreshCw size={17} /></Button>
          <Button asChild variant="outline" className={btn}><Link href={`/modules/${moduleId}${selected ? `?lesson=${encodeURIComponent(selected)}` : ""}`} target="_blank" rel="noopener noreferrer"><Eye size={16} />Как видит ученик</Link></Button>
          <Button className={btn} disabled={!!busy} variant={moduleMeta.is_active ? "outline" : "primary"} onClick={() => {
            if (moduleMeta.is_archived) { void mutate("", "PATCH", { is_archived: false }, "Модуль восстановлен в черновики"); return; }
            if (moduleMeta.is_active) setDialog({ kind: "confirm", title: "Снять модуль с публикации?", description: "Ученики временно потеряют доступ к материалам. Их результаты останутся на месте. Вы сможете опубликовать модуль снова.", action: () => mutate("", "PATCH", { is_active: false }, "Модуль снят с публикации") });
            else void mutate("", "PATCH", { is_active: true }, "Модуль опубликован");
          }}>{moduleMeta.is_archived ? <RotateCcw size={16} /> : <CheckCircle2 size={16} />}{moduleMeta.is_archived ? "Восстановить модуль" : moduleMeta.is_active ? "Снять с публикации" : "Опубликовать"}</Button>
        </div>
      </header>
      {moduleMeta.is_archived && <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Модуль в архиве. Файлы, версии и результаты сохранены. Восстановите его, чтобы продолжить редактирование.</div>}
      <nav ref={tabsRef} aria-label="Разделы редактора" className="mt-7 flex gap-1 overflow-x-auto border-b border-zinc-200">
        {([{ id: "materials", name: "Материалы", Icon: BookOpen }, { id: "tests", name: "Тесты", Icon: GraduationCap }, { id: "settings", name: "Настройки и доступ", Icon: Settings2 }, { id: "import", name: "Обновить из ZIP", Icon: RefreshCw }, { id: "archive", name: `Архив${archiveCount ? ` · ${archiveCount}` : ""}`, Icon: Archive }] as const).map(({ id, name, Icon }) => <button type="button" key={id} disabled={!!busy} onClick={() => changeTab(id)} aria-current={tab === id ? "page" : undefined} className={cn("flex shrink-0 items-center gap-2 border-b-2 px-4 py-3.5 text-sm font-medium transition-colors disabled:opacity-50", tab === id ? "border-amber-500 text-zinc-950" : "border-transparent text-zinc-500 hover:text-zinc-900")}><Icon size={16} />{name}{((id === "settings" && settingsDirty) || (id === "tests" && quizDirty)) && <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />}</button>)}
      </nav>
      {error && !dialog && <div role="alert" className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"><span className="flex-1">{error}</span>{conflict && <button type="button" className="font-medium underline" onClick={() => { if (!dirty || window.confirm("Обновить данные без сохранения текущего черновика?")) { setDialog(null); void load(true); } }}>Обновить данные</button>}<button type="button" aria-label="Скрыть сообщение" onClick={() => setError(null)}><X size={16} /></button></div>}
      {(tab === "materials" || tab === "archive") && <div className="mt-6 grid items-start gap-6 lg:grid-cols-[290px_minmax(0,1fr)]">
        <aside className="overflow-hidden rounded-2xl border border-zinc-200 bg-white lg:sticky lg:top-24">
          <div className="flex items-center justify-between border-b border-zinc-100 p-4"><h2 className="text-sm font-semibold">Структура модуля</h2><span className="text-xs text-zinc-400">{activeLessons.length}</span></div>
          <nav aria-label="Раздел для редактирования" className="max-h-[60vh] space-y-1 overflow-y-auto p-2">
            <button type="button" disabled={!!busy} onClick={() => { setSelected(null); setTab("materials"); }} className={cn("flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm", !selected && tab === "materials" ? "bg-amber-50 font-medium text-zinc-950" : "text-zinc-600 hover:bg-zinc-50")}><Folder size={18} className="shrink-0 text-amber-600" /><span>Общие файлы</span><span className="ml-auto text-xs text-zinc-400">{data.assets.filter(a => !a.is_archived && !a.submodule_id).length}</span></button>
            {activeLessons.map((lesson, index) => <div key={lesson.id} className={cn("group flex items-center rounded-xl", lesson.id === selected && tab === "materials" ? "bg-amber-50" : "hover:bg-zinc-50")}>
              <button type="button" aria-label={`Материал: ${lesson.title}`} disabled={!!busy} onClick={() => { setSelected(lesson.id); setTab("materials"); }} className="flex min-w-0 flex-1 items-start gap-2.5 px-3 py-3 text-left text-sm"><span className="mt-0.5 shrink-0 text-zinc-400">{lesson.is_folder ? <Folder size={17} /> : <BookOpen size={17} />}</span><span className="min-w-0 break-words leading-5 text-zinc-700">{lesson.title}<span className="mt-1 block text-[11px] text-zinc-400">{lesson.is_folder ? "Каталог" : lesson.requires_quiz ? "Урок с тестом" : "Урок"}</span></span></button>
              <div className="mr-1 flex shrink-0 flex-col"><button type="button" aria-label={`Поднять «${lesson.title}»`} title="Выше" disabled={locked || index === 0} onClick={() => void reorder(lesson, -1)} className="rounded p-1.5 text-zinc-400 hover:bg-white hover:text-zinc-900 disabled:opacity-20"><ArrowUp size={13} /></button><button type="button" aria-label={`Опустить «${lesson.title}»`} title="Ниже" disabled={locked || index === activeLessons.length - 1} onClick={() => void reorder(lesson, 1)} className="rounded p-1.5 text-zinc-400 hover:bg-white hover:text-zinc-900 disabled:opacity-20"><ArrowDown size={13} /></button></div>
            </div>)}
          </nav>
          <div className="grid gap-2 border-t border-zinc-100 p-3"><Button variant="outline" disabled={locked} className={btn} onClick={() => openLesson()}><Plus size={16} />Добавить урок</Button><Button variant="ghost" disabled={locked} className={btn} onClick={() => openLesson(undefined, true)}><Folder size={16} />Создать каталог файлов</Button></div>
        </aside>
        <section className="min-w-0 space-y-5">
          <section className="rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="mb-1 text-xs text-zinc-500">{tab === "archive" ? "Можно восстановить в любой момент" : selectedLesson ? selectedLesson.is_folder ? "Каталог материалов" : "Учебный материал" : "Доступны из обзора модуля"}</p><h2 className="break-words text-xl font-semibold tracking-tight">{tab === "archive" ? "Архив материалов" : selectedLesson?.title || "Общие файлы модуля"}</h2></div>{tab === "materials" && selectedLesson && <div className="flex items-center gap-1"><Button variant="ghost" size="sm" className={btn} disabled={locked} onClick={() => openLesson(selectedLesson)}><Pencil size={14} />Редактировать</Button><button type="button" aria-label="Переместить урок в архив" title="В архив" disabled={locked} onClick={() => archiveLesson(selectedLesson)} className="rounded-lg p-2 text-zinc-400 hover:bg-rose-50 hover:text-rose-700 disabled:opacity-40"><Archive size={17} /></button></div>}</div>
            {tab === "materials" && selectedLesson && !selectedLesson.is_folder && <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-zinc-50 px-4 py-3"><p className="text-xs leading-relaxed text-zinc-500">{selectedLesson.content_length ? `${selectedLesson.content_length.toLocaleString("ru-RU")} символов текста · ` : selectedLesson.has_external_content ? "Текст из хранилища · " : "Текст урока пока не добавлен · "}{selectedLesson.requires_quiz ? "Тест обязателен" : "Завершение по прочтению"}</p><div className="flex flex-wrap items-center gap-4"><button type="button" className="flex items-center gap-1.5 text-xs font-medium text-zinc-600 hover:underline" onClick={() => void openTextHistory(selectedLesson)}><History size={14} />История текста · v{selectedLesson.content_version}</button><button type="button" className="flex items-center gap-1.5 text-xs font-medium text-amber-800 hover:underline" onClick={() => changeTab("tests")}>Вопросы и тест<ArrowRight size={13} /></button></div></div>}
            {tab === "materials" && <div onDragOver={event => { event.preventDefault(); if (!locked) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (!locked) void upload(Array.from(event.dataTransfer.files)); }} className={cn("mt-5 rounded-xl border-2 border-dashed px-5 py-6 text-center transition-colors", dragging ? "border-amber-500 bg-amber-50" : "border-zinc-200 bg-zinc-50/50", locked && "opacity-50")}>
              <UploadCloud size={27} className="mx-auto mb-2 text-amber-600" /><p className="text-sm font-medium text-zinc-800">Перетащите файлы сюда</p><p className="mt-1 text-xs text-zinc-500">или выберите несколько файлов. ZIP для обновления всего модуля — в отдельной вкладке.</p><Button variant="outline" size="sm" className={`mt-3 ${btn}`} disabled={locked} onClick={() => uploadInput.current?.click()}><FilePlus2 size={15} />Выбрать файлы</Button>
              <input ref={uploadInput} type="file" multiple aria-label="Добавить файлы" className="sr-only" disabled={locked} onChange={event => { const selectedFiles = Array.from(event.target.files || []); event.target.value = ""; void upload(selectedFiles); }} />
              <input ref={replaceInput} type="file" aria-label="Новая версия файла" className="sr-only" disabled={locked} onChange={event => { const file = event.target.files?.[0]; const asset = replacement.current; event.target.value = ""; if (file && asset) void upload([file], asset); }} />
            </div>}
            {tasks.length > 0 && <div aria-live="polite" className="mt-4 rounded-xl border border-zinc-200 p-3"><div className="mb-2 flex items-center justify-between text-xs"><span className="font-medium text-zinc-700">Загружено {tasks.filter(t => t.state === "done").length} из {tasks.length}</span>{busy === "upload" ? <button type="button" onClick={() => { stopQueue.current = true; }} className="text-amber-800 underline">Остановить после текущего</button> : <button type="button" aria-label="Скрыть очередь загрузки" onClick={() => setTasks([])} className="p-1"><X size={14} /></button>}</div><div className="max-h-44 space-y-2 overflow-auto">{tasks.map((task, i) => <div key={i} className="text-xs"><div className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate text-zinc-600">{task.name}</span>{task.state === "done" ? <Check size={14} className="text-emerald-700" /> : <span className={task.state === "error" ? "text-rose-700" : "text-zinc-400"}>{task.state === "uploading" ? task.percent === 100 ? "Сохраняем…" : `${task.percent}%` : task.state === "waiting" ? "В очереди" : task.state === "error" ? "Ошибка" : "Не загружен"}</span>}</div>{task.state === "uploading" && <div className="mt-1 h-1 rounded bg-zinc-100"><div className="h-1 rounded bg-amber-500" style={{ width: `${task.percent}%` }} /></div>}{task.error && <p className="mt-1 text-rose-700">{task.error}</p>}</div>)}</div></div>}
            {tab === "archive" && archivedLessons.length > 0 && <div className="mt-5 space-y-2"><h3 className="mb-3 text-xs font-medium text-zinc-500">Уроки и каталоги</h3>{archivedLessons.map(lesson => <div key={lesson.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-zinc-200 p-3"><Archive size={18} className="text-zinc-400" /><span className="min-w-0 flex-1 break-words text-sm text-zinc-700">{lesson.title}</span><Button variant="ghost" size="sm" disabled={locked} className={btn} onClick={() => void mutate(`/lessons/${lesson.id}`, "PATCH", { is_archived: false }, "Материал восстановлен")}><RotateCcw size={14} />Восстановить</Button></div>)}</div>}
            <div className="mt-5 flex flex-wrap items-center justify-between gap-3"><label className="flex min-w-48 flex-1 items-center gap-2 rounded-xl border border-zinc-200 px-3 text-zinc-400"><Search size={16} /><input aria-label="Поиск файлов" placeholder="Поиск по названию файла…" value={query} onChange={e => setQuery(e.target.value)} className="h-10 w-full min-w-0 bg-transparent text-sm text-zinc-800 outline-none" /></label><span className="text-xs text-zinc-400">{formatFileCount(files.length)}</span></div>
            {checked.size > 0 && <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs"><span>Выбрано: {checked.size}</span><div className="flex gap-3"><button type="button" disabled={locked} onClick={() => tab === "archive" ? void mutate("/assets/archive", "POST", { ids: [...checked], is_archived: false }, "Файлы восстановлены").then(ok => { if (ok) setChecked(new Set()); }) : archiveFiles([...checked])} className="font-medium text-amber-900 underline">{tab === "archive" ? "Восстановить выбранные" : "В архив"}</button><button type="button" onClick={() => setChecked(new Set())} className="text-zinc-500">Снять выбор</button></div></div>}
            <div className="mt-3 overflow-visible rounded-xl border border-zinc-200">
              {files.length > 0 && <div className="flex items-center gap-3 rounded-t-xl border-b border-zinc-200 bg-zinc-50 px-4 py-2 text-xs text-zinc-500"><input type="checkbox" aria-label="Выбрать все показанные файлы" checked={files.every(a => checked.has(a.asset_id))} onChange={e => setChecked(e.target.checked ? new Set(files.map(a => a.asset_id)) : new Set())} className="h-4 w-4 accent-amber-600" /><span>Название</span><span className="ml-auto">Действия</span></div>}
              {files.map((asset, index) => <div key={asset.asset_id} className={cn("flex items-center gap-2 border-b border-zinc-100 px-3 py-3 last:rounded-b-xl last:border-b-0 sm:gap-3 sm:px-4", previewId === asset.asset_id && "bg-amber-50/70")}>
                <input type="checkbox" aria-label={`Выбрать ${asset.original_filename}`} checked={checked.has(asset.asset_id)} onChange={e => setChecked(prev => { const next = new Set(prev); if (e.target.checked) next.add(asset.asset_id); else next.delete(asset.asset_id); return next; })} className="h-4 w-4 shrink-0 accent-amber-600" />
                <button type="button" onClick={() => openPreview(asset)} className="flex min-w-0 flex-1 items-center gap-3 text-left"><span className="hidden shrink-0 rounded-lg bg-zinc-50 p-2 text-zinc-500 sm:block"><MaterialIcon name={asset.original_filename} /></span><span className="min-w-0"><span className="block break-words text-sm font-medium leading-5 text-zinc-800">{asset.original_filename}</span><span className="mt-1 block text-[11px] text-zinc-400">{fileExtension(asset.original_filename).toUpperCase() || "Файл"} · {formatBytes(asset.size_bytes)} · v{asset.version}</span></span></button>
                {tab === "archive" ? <button type="button" disabled={locked} title="Восстановить файл" aria-label={`Восстановить ${asset.original_filename}`} onClick={() => void mutate(`/assets/${asset.asset_id}`, "PATCH", { is_archived: false }, "Файл восстановлен")} className="rounded-lg p-2 text-emerald-700 hover:bg-emerald-50 disabled:opacity-40"><RotateCcw size={17} /></button> : <>
                  <button type="button" aria-label={`Скачать ${asset.original_filename}`} title="Скачать" onClick={() => void download(asset)} className="hidden rounded-lg p-2 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-800 sm:block"><Download size={16} /></button>
                  <details className="relative shrink-0" onClick={e => { if ((e.target as HTMLElement).closest("button")) e.currentTarget.removeAttribute("open"); }}>
                    <summary aria-label={`Действия с ${asset.original_filename}`} title="Действия с файлом" className="list-none cursor-pointer rounded-lg p-2 text-zinc-500 hover:bg-zinc-100"><MoreHorizontal size={19} /></summary>
                    <div className="absolute right-0 top-10 z-30 w-56 rounded-xl border border-zinc-200 bg-white p-1.5 shadow-xl">
                      {[
                        { label: "Посмотреть", Icon: Eye, action: () => openPreview(asset), disabled: false },
                        { label: "Скачать оригинал", Icon: Download, action: () => void download(asset), disabled: false },
                        { label: "Заменить файл", Icon: UploadCloud, action: () => { replacement.current = asset; replaceInput.current?.click(); }, disabled: locked },
                        { label: "Переименовать", Icon: Pencil, action: () => { setDraftTitle(asset.original_filename.split(/[\\/]/).pop() || asset.original_filename); setDialog({ kind: "rename", asset }); }, disabled: locked },
                        { label: "Переместить", Icon: Folder, action: () => { setDraftTarget(asset.submodule_id || ""); setDialog({ kind: "move", asset }); }, disabled: locked },
                        { label: "История версий", Icon: History, action: () => void showVersions(asset), disabled: false },
                        { label: "Выше в списке", Icon: ArrowUp, action: () => void reorderFile(asset, -1), disabled: locked || index === 0 || !!query },
                        { label: "Ниже в списке", Icon: ArrowDown, action: () => void reorderFile(asset, 1), disabled: locked || index === files.length - 1 || !!query },
                        { label: "Переместить в архив", Icon: Archive, action: () => archiveFiles([asset.asset_id]), disabled: locked },
                      ].map(({ label, Icon, action, disabled }) => <button type="button" key={label} disabled={disabled} onClick={action} className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-xs text-zinc-700 hover:bg-zinc-50 disabled:opacity-30"><Icon size={15} className="text-zinc-400" />{label}</button>)}
                    </div>
                  </details>
                </>}
              </div>)}
              {!files.length && <div className="p-9 text-center"><Folder size={28} className="mx-auto mb-3 text-zinc-300" /><p className="text-sm font-medium text-zinc-600">{query ? "Файлы не найдены" : tab === "archive" ? "Архив файлов пуст" : "Здесь пока нет файлов"}</p><p className="mt-1 text-xs leading-relaxed text-zinc-400">{query ? "Попробуйте другое название." : tab === "archive" ? "Удалённые из обучения материалы будут здесь." : "Добавляйте материалы по одному или сразу несколько — без переимпорта модуля."}</p></div>}
            </div>
          </section>
          {preview && <div ref={previewRef} className="scroll-mt-24"><AssetPreview asset={preview} onClose={() => setPreviewId(null)} /></div>}
          <p className="flex items-start gap-2 px-1 text-xs leading-relaxed text-zinc-500"><ShieldCheck size={16} className="shrink-0 text-emerald-700" />Замена файлов сохраняет их адреса в LMS. Архив не удаляет данные из хранилища. Для каждой замены доступна предыдущая версия.</p>
        </section>
      </div>}
      {tab === "tests" && <ModuleQuizEditor key={quizReset} moduleId={moduleId} revision={moduleMeta.content_revision} lessons={data.lessons} initialLessonId={selected} locked={locked} onWorkspace={accept} onDirtyChange={setQuizDirty} onBusyChange={quizWorking} />}
      {tab === "settings" && <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]"><form onSubmit={e => { e.preventDefault(); void mutate("", "PATCH", moduleDraft); }} className="space-y-5 rounded-2xl border border-zinc-200 bg-white p-5 sm:p-7"><h2 className="text-lg font-semibold">О модуле</h2><label className="block space-y-2 text-sm font-medium">Название<input required maxLength={300} disabled={locked} className={input} value={moduleDraft.title} onChange={e => setModuleDraft(d => ({ ...d, title: e.target.value }))} /></label><label className="block space-y-2 text-sm font-medium">Описание<textarea rows={5} maxLength={5000} disabled={locked} className={input} value={moduleDraft.description} placeholder="Что изучит ученик и как устроено обучение" onChange={e => setModuleDraft(d => ({ ...d, description: e.target.value }))} /></label><label className="block space-y-2 text-sm font-medium">Категория<input maxLength={200} disabled={locked} className={input} value={moduleDraft.category} placeholder="Например, Производство" onChange={e => setModuleDraft(d => ({ ...d, category: e.target.value }))} /></label><fieldset className="space-y-4 border-t border-zinc-100 pt-5" disabled={locked}><legend className="text-sm font-semibold">Доступ к опубликованному модулю</legend><label className="block space-y-2 text-sm font-medium">Аудитория<select aria-label="Аудитория" className={input} value={moduleDraft.visibility} onChange={e => setModuleDraft(d => ({ ...d, visibility: e.target.value }))}><option value="public">Все ученики</option><option value="restricted">Ученики с выбранными тегами</option><option value="hidden">Только администраторы</option></select></label>{moduleDraft.visibility === "restricted" && <div className="space-y-3">{tagsError && <p role="alert" className="text-xs text-rose-700">{tagsError}</p>}<div className="max-h-56 space-y-2 overflow-auto rounded-xl border border-zinc-200 p-3">{tags.length ? tags.map(tag => <label key={tag.id} className="flex items-center gap-3 p-1 text-sm"><input type="checkbox" className="h-4 w-4 accent-amber-600" checked={moduleDraft.tag_ids.includes(tag.id)} onChange={e => setModuleDraft(d => ({ ...d, tag_ids: e.target.checked ? [...d.tag_ids, tag.id] : d.tag_ids.filter(id => id !== tag.id) }))} />{tag.name}</label>) : <p className="text-xs leading-6 text-zinc-500">Теги ещё не созданы. Управляйте ими в разделе пользователей.</p>}</div><p className="text-xs leading-6 text-zinc-500">{moduleDraft.tag_ids.length ? "Достаточно совпадения любого выбранного тега. Теги назначаются ученикам в разделе пользователей." : "Пока теги не выбраны, модуль недоступен ученикам."}</p></div>}</fieldset><div className="flex flex-wrap items-center gap-3"><Button type="submit" className={btn} disabled={locked || !settingsDirty || !moduleDraft.title.trim()}><Save size={16} />{busy === "save" ? "Сохраняем…" : "Сохранить настройки"}</Button>{settingsDirty && <span className="text-xs text-amber-700">Есть несохранённые изменения</span>}</div></form><div className="space-y-5"><section className="rounded-2xl border border-zinc-200 bg-white p-6"><h2 className="text-sm font-semibold">Кому доступен модуль</h2><p className="my-3 text-sm leading-relaxed text-zinc-500">{!moduleMeta.is_active ? "Черновик виден только администраторам." : moduleMeta.visibility === "restricted" ? "Доступ определяется тегами аудитории." : moduleMeta.visibility === "hidden" ? "Модуль скрыт от учеников." : "Модуль доступен всем ученикам."}</p><p className="text-xs leading-6 text-zinc-500">Доступ задаётся в форме слева и применяется после сохранения настроек. Черновики и архивные модули никогда не видны ученикам.</p></section><section className="rounded-2xl border border-zinc-200 bg-white p-6"><h2 className="text-sm font-semibold">Архив модуля</h2><p className="my-3 text-sm leading-relaxed text-zinc-500">Уберите устаревший модуль из каталога без удаления файлов, результатов и истории обучения.</p><Button variant="outline" disabled={locked} className={btn} onClick={() => setDialog({ kind: "confirm", title: "Переместить модуль в архив?", description: "Модуль исчезнет из каталога учеников. Все материалы, версии и результаты сохранятся. Для возврата используйте архив в списке модулей.", action: () => mutate("", "PATCH", { is_archived: true }, "Модуль перемещён в архив") })}><Archive size={16} />В архив</Button></section></div></div>}
      {tab === "import" && <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]"><section className="rounded-2xl border border-zinc-200 bg-white p-5 sm:p-7"><div className="mb-5 flex items-center gap-3"><span className="rounded-xl bg-emerald-50 p-3 text-emerald-700"><ShieldCheck size={23} /></span><div><h2 className="text-xl font-semibold">Обновление без потери прогресса</h2><p className="mt-1 text-sm text-zinc-500">Обновляется этот модуль, а не создаётся его копия.</p></div></div><ul className="space-y-3 text-sm leading-relaxed text-zinc-600">{["Существующие уроки и файлы сопоставляются по исходному пути. Для старого импорта — по однозначному совпадению названия и типа.", "Новые материалы добавляются, изменённые файлы получают новую версию. Отсутствующие в ZIP материалы остаются на месте.", "Ручные названия, порядок, архивные материалы и тесты не перезаписываются. Уже пройденное обучение остаётся пройденным."].map(line => <li key={line} className="flex gap-2.5"><Check size={17} className="mt-0.5 shrink-0 text-emerald-700" /><span>{line}</span></li>)}</ul><label className="mt-6 block cursor-pointer rounded-xl border-2 border-dashed border-zinc-200 bg-zinc-50 p-7 text-center"><UploadCloud size={28} className="mx-auto mb-3 text-amber-600" /><span className="block text-sm font-medium">{importFile?.name || "Выберите обновлённый ZIP-архив"}</span><span className="mt-1 block text-xs text-zinc-400">{importFile ? formatBytes(importFile.size) : "До 1 ГБ. Для большей загрузки используйте общий импорт."}</span><input type="file" accept=".zip,application/zip" disabled={locked || jobRunning} className="sr-only" aria-label="ZIP для обновления модуля" onChange={e => { setImportFile(e.target.files?.[0] || null); }} /></label>{busy === "import-upload" && <div role="status" className="mt-4"><div className="mb-2 flex justify-between text-xs text-zinc-500"><span>{importPercent === 100 ? "Сохраняем ZIP в хранилище…" : "Загружаем архив…"}</span><span>{importPercent}%</span></div><div className="h-1.5 rounded bg-zinc-100"><div className="h-full rounded bg-amber-500" style={{ width: `${importPercent}%` }} /></div></div>}<Button disabled={locked || jobRunning || !importFile} onClick={() => void startReimport()} className={`mt-5 ${btn}`}>{busy === "import-upload" || jobRunning ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}{jobRunning ? "Обновление выполняется" : "Обновить этот модуль"}</Button><p className="mt-3 text-xs leading-relaxed text-zinc-400">После загрузки работа продолжится в фоне. До успешного сохранения ученики видят предыдущую версию. Параллельные изменения не будут затёрты.</p>
        {job && <div aria-live="polite" className={cn("mt-6 rounded-xl border p-4", job.status === "finished" && job.result?.ok ? "border-emerald-200 bg-emerald-50" : ["failed", "stopped", "missing"].includes(job.status) || job.result?.canceled ? "border-rose-200 bg-rose-50" : "border-amber-200 bg-amber-50")}><p className="text-sm font-semibold">{job.status === "finished" && job.result?.ok ? "Модуль обновлён. Прогресс сохранён." : job.result?.canceled || job.status === "canceled" ? "Обновление отменено" : job.status === "missing" ? "Статус задачи недоступен. Проверьте журнал импорта." : job.status === "failed" || job.status === "stopped" ? "Не удалось завершить обновление" : job.status === "queued" ? "Архив в очереди обработки" : "Обновляем материалы…"}</p>{jobRunning && <p className="mt-2 break-words text-xs text-zinc-600">{job.detail || "Ожидаем свободный обработчик. Страницу можно закрыть."}</p>}{job.error_message && <p className="mt-2 text-xs leading-relaxed text-rose-700">{job.error_message}</p>}{job.error_hint && <p className="mt-2 text-xs text-zinc-600">{job.error_hint}</p>}{job.result?.report && <><div className="mt-3 grid grid-cols-2 gap-2 text-xs"><span>Новых уроков: {job.result.report.lessons_added || 0}</span><span>Обновлено уроков: {job.result.report.lessons_updated || 0}</span><span>Новых файлов: {job.result.report.files_added || 0}</span><span>Новых версий: {job.result.report.files_updated || 0}</span><span>Без изменений: {job.result.report.files_unchanged || 0}</span><span>Сохранено прежних уроков: {job.result.report.lessons_kept || 0}</span></div>{job.result.report.warnings?.map((warning, i) => <p key={i} className="mt-3 text-xs leading-relaxed text-amber-900">{warning}</p>)}</>}<Link href="/admin/import" className="mt-3 inline-flex items-center gap-1 text-xs font-medium underline">Журнал задач<ChevronRight size={13} /></Link></div>}
      </section><aside className="space-y-4"><div className="rounded-2xl border border-zinc-200 bg-white p-6"><h3 className="flex items-center gap-2 text-sm font-semibold"><Info size={17} className="text-amber-700" />Как подготовить архив</h3><p className="mt-3 text-sm leading-7 text-zinc-500">Сохраняйте названия папок и файлов, если это те же материалы. Папки верхнего уровня становятся каталогами, файлы в корне — уроками, папка <code className="rounded bg-zinc-100 px-1 text-xs">_module</code> — общими файлами.</p><p className="mt-3 text-sm leading-7 text-zinc-500">Переименованные неоднозначные материалы не объединяются автоматически: старые сохраняются, новые добавляются. После импорта проверьте отчёт и при необходимости переместите лишнее в архив.</p></div><div className="rounded-2xl bg-emerald-50 p-6 text-sm leading-7 text-emerald-900"><strong>Нужно заменить один файл?</strong><p className="mt-1 text-emerald-800/80">Откройте «Материалы» → меню файла → «Заменить файл». Полный импорт для этого не нужен.</p></div></aside></div>}
    </>}
    <Modal open={!!dialog} title={dialogTitle} onClose={closeDialog} disableClose={!!busy} className="max-w-3xl" footer={dialog?.kind === "versions" || dialog?.kind === "textVersions" ? <Button variant="outline" className={btn} onClick={closeDialog}>Закрыть</Button> : <div className="flex justify-end gap-2"><Button variant="ghost" className={btn} onClick={closeDialog} disabled={!!busy}>Отмена</Button><Button className={btn} onClick={() => void saveDialog()} disabled={!!busy || ((dialog?.kind === "lesson" || dialog?.kind === "rename") && !draftTitle.trim())}>{busy ? <Loader2 size={16} className="animate-spin" /> : dialog?.kind === "confirm" ? <Archive size={16} /> : <Save size={16} />}{busy ? "Сохраняем…" : dialog?.kind === "confirm" ? "Подтвердить" : "Сохранить"}</Button></div>}>
      {error && <p role="alert" className="mb-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
      {dialog?.kind === "confirm" && <p className="text-sm leading-7 text-zinc-600">{dialog.description}</p>}
      {(dialog?.kind === "lesson" || dialog?.kind === "rename") && <label className="mb-5 block space-y-2 text-sm font-medium">{dialog.kind === "rename" ? "Имя файла с расширением" : "Название"}<input autoFocus maxLength={dialog.kind === "rename" ? 400 : 300} value={draftTitle} onChange={e => setDraftTitle(e.target.value)} className={input} disabled={!!busy} /></label>}
      {dialog?.kind === "lesson" && <div className="space-y-5">{!dialog.folder && <><label className="block space-y-2 text-sm font-medium">Раздел <span className="font-normal text-zinc-400">(необязательно)</span><input className={input} value={draftOutline} maxLength={1000} placeholder="Например, Основы / Подготовка" onChange={e => setDraftOutline(e.target.value)} /></label><div><div className="mb-2 flex justify-between gap-3"><label htmlFor="lesson-content" className="text-sm font-medium">Текст урока <span className="font-normal text-zinc-400">· Markdown</span></label><button type="button" onClick={() => setShowMarkdown(v => !v)} className="text-xs text-amber-800 underline">{showMarkdown ? "Редактировать текст" : "Предпросмотр урока"}</button></div>{showMarkdown ? <div className="space-y-3"><p className="text-xs leading-6 text-zinc-500">Так выглядит черновик урока. Изменения станут видны ученикам только после сохранения.</p><LessonPresentation key={`${dialog.lesson?.id || "new"}:${draftPresentation}:${draftPrimary}`} lesson={{ id: dialog.lesson?.id || "new", content: draftContent, content_mode: draftMode, presentation_mode: draftPresentation, primary_asset_id: draftPrimary || null }} assets={data?.assets.filter(a => !a.is_archived && a.submodule_id === dialog.lesson?.id) || []} /></div> : <textarea id="lesson-content" rows={10} maxLength={500000} className={`${input} font-mono text-xs leading-6`} value={draftContent} onChange={e => { setDraftContent(e.target.value); setDraftMode("manual"); }} placeholder="Добавьте объяснения, инструкции, списки и ссылки…" />}</div><div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900"><div className="flex items-center gap-2 font-medium"><ShieldCheck size={17} />{draftMode === "manual" ? "Текст защищён от замены при импорте" : "Текст обновляется из ZIP"}</div><p className="mt-2 text-xs leading-6">Ручное изменение автоматически включает защиту. Предыдущие версии сохраняются в истории текста.</p>{dialog.lesson?.source_path && <label className="mt-3 flex items-start gap-2 text-xs leading-6"><input type="checkbox" className="mt-1 h-4 w-4 shrink-0 accent-amber-600" checked={draftMode === "import"} onChange={e => setDraftMode(e.target.checked ? "import" : "manual")} /><span>Разрешить следующему ZIP-импорту заменить этот текст</span></label>}</div><div className="space-y-4 rounded-xl border border-zinc-200 p-4"><label className="block space-y-2 text-sm font-medium">Что открывать первым<select aria-label="Что открывать первым" className={input} value={draftPresentation} onChange={e => setDraftPresentation(e.target.value as typeof draftPresentation)}><option value="auto">Авто: файл, если он есть; иначе текст</option><option value="material">Основной файл</option><option value="text">Текст урока</option></select></label>{dialog.lesson && data?.assets.some(a => !a.is_archived && a.submodule_id === dialog.lesson?.id) && <label className="block space-y-2 text-sm font-medium">Основной файл<select aria-label="Основной файл" className={input} value={draftPrimary} onChange={e => setDraftPrimary(e.target.value)}><option value="">Первый файл по порядку</option>{data.assets.filter(a => !a.is_archived && a.submodule_id === dialog.lesson?.id).map(a => <option key={a.asset_id} value={a.asset_id}>{a.original_filename}</option>)}</select></label>}<p className="text-xs leading-6 text-zinc-500">Документ и конспект переключаются вкладками, а не показываются длинной лентой. Тест настраивается отдельно во вкладке «Тесты» этого же редактора.</p></div></>}{dialog.folder && <p className="text-sm leading-7 text-zinc-500">Каталог объединяет файлы и вложенные папки. Он не требует теста и не меняет количество обязательных уроков.</p>}</div>}
      {dialog?.kind === "rename" && <p className="text-xs leading-relaxed text-zinc-500">Меняется отображаемое имя, а не содержимое и не ссылка на файл. Сохраните исходное расширение.</p>}
      {dialog?.kind === "move" && <div className="space-y-4"><p className="break-words text-sm text-zinc-500">{dialog.asset.original_filename}</p><label className="block space-y-2 text-sm font-medium">Куда переместить<select className={input} value={draftTarget} onChange={e => setDraftTarget(e.target.value)}><option value="">Общие файлы модуля</option>{activeLessons.map(l => <option key={l.id} value={l.id}>{l.title}</option>)}</select></label><p className="text-xs text-zinc-500">Содержимое, ссылка на файл и его версии сохранятся.</p></div>}
      {dialog?.kind === "textVersions" && <div className="space-y-4"><div><p className="break-words text-sm font-medium">{dialog.lesson.title}</p><p className="mt-2 text-xs text-zinc-500">Текущая версия: {dialog.lesson.content_version}. Восстановленный текст будет защищён от замены ZIP-импортом.</p></div>{versionsLoading ? <p role="status" className="py-4 text-sm text-zinc-500">Загружаем историю…</p> : textVersions.length ? <div className="max-h-56 space-y-2 overflow-y-auto">{textVersions.map(version => <button key={version.version} type="button" aria-pressed={textPreview?.version === version.version} onClick={() => void previewTextVersion(dialog.lesson, version.version)} className={cn("flex w-full flex-wrap items-center justify-between gap-2 rounded-xl border p-3 text-left", textPreview?.version === version.version ? "border-amber-400 bg-amber-50" : "border-zinc-200 hover:bg-zinc-50")}><span className="text-sm font-medium">Версия {version.version}</span><span className="text-xs text-zinc-500">Снимок перед изменением · {new Date(version.created_at).toLocaleString("ru-RU")}</span></button>)}</div> : <p className="py-4 text-sm text-zinc-500">Текст ещё не менялся. Предыдущие версии появятся здесь после сохранения изменений.</p>}{textLoading && <p role="status" className="text-sm text-zinc-500">Загружаем текст…</p>}{textPreview && <><div className="max-h-80 overflow-y-auto whitespace-pre-wrap break-words rounded-xl border border-zinc-200 bg-zinc-50 p-4 text-sm leading-7">{textPreview.content || "Пустой текст"}</div><Button variant="outline" className={btn} disabled={locked || dialog.lesson.is_archived} onClick={() => { if (window.confirm(`Восстановить текст версии ${textPreview.version}? Текущий текст останется в истории.`)) void mutate(`/lessons/${dialog.lesson.id}/restore-version`, "POST", { version: textPreview.version }, "Текст восстановлен", dialog.revision).then(ok => { if (ok) setDialog(null); }); }}><RotateCcw size={15} />Восстановить версию {textPreview.version}</Button></>}</div>}
      {dialog?.kind === "versions" && <div className="space-y-3"><p className="break-words text-sm font-medium">{dialog.asset.original_filename}</p><div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">Текущая версия: {dialog.asset.version} · {formatBytes(dialog.asset.size_bytes)}</div>{versionsLoading ? <p role="status" className="flex items-center gap-2 py-4 text-sm text-zinc-500"><Loader2 className="animate-spin" size={16} />Загружаем историю…</p> : versions.length ? versions.map(version => <div key={version.version} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-zinc-200 p-4"><div><p className="text-sm font-medium">Версия {version.version}</p><p className="mt-1 text-xs text-zinc-500">{new Date(version.created_at).toLocaleString("ru-RU")} · {formatBytes(version.size_bytes)}</p></div><Button variant="outline" className={btn} size="sm" disabled={locked} onClick={() => { if (window.confirm(`Восстановить версию ${version.version}? Текущая версия тоже останется в истории.`)) void mutate(`/assets/${dialog.asset.asset_id}/restore-version`, "POST", { version: version.version }, "Версия восстановлена").then(ok => { if (ok) setDialog(null); }); }}><RotateCcw size={14} />Восстановить</Button></div>) : <p className="py-5 text-sm text-zinc-500">Файл ещё не заменяли. Предыдущие версии появятся здесь после замены.</p>}<p className="pt-2 text-xs leading-relaxed text-zinc-500">Восстановление создаёт новую текущую версию. Ничто из истории не удаляется.</p></div>}
    </Modal>
  </div></AppShell>;
}
