"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, FileArchive, Loader2, RefreshCw, UploadCloud, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import { throttleRefresh } from "@/lib/refresh-throttle";

type Stage = "queued" | "upload" | "enqueue" | "done" | "failed";

type Upload = {
  name: string;
  size: number;
  percent: number;
  stage: Stage;
  detail: string;
  jobId?: string;
  moduleId?: string;
};

type JobRow = {
  job_id: string;
  status: string;
  status_label?: string;
  filename?: string | null;
  module_title?: string | null;
  module_id?: string | null;
  stage?: string | null;
  detail?: string | null;
  created_at?: string | null;
  error_message?: string | null;
};

const btn = "gap-2 rounded-xl text-sm font-medium normal-case tracking-normal";
const CHUNK = 64 * 1024 * 1024;

function putFile(url: string, body: Blob, contentType: string, onProgress: (loaded: number) => void, headers?: Record<string, string> | null): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url, true);
    xhr.upload.onprogress = (event) => onProgress(Number(event.loaded || 0));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.getResponseHeader("ETag") || xhr.getResponseHeader("etag") || "");
      else reject(new Error(`Хранилище отклонило загрузку: HTTP ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("Нет связи с хранилищем файлов"));
    xhr.setRequestHeader("Content-Type", contentType);
    for (const [key, value] of Object.entries(headers || {})) if (key && value) xhr.setRequestHeader(key, String(value));
    xhr.send(body);
  });
}

function statusTone(status: string): string {
  const s = status.toLowerCase();
  if (s === "finished" || s === "done") return "bg-emerald-50 text-emerald-800";
  if (s === "failed" || s === "canceled" || s === "cancelled") return "bg-rose-50 text-rose-700";
  if (s === "started" || s === "queued" || s === "deferred" || s === "scheduled") return "bg-amber-50 text-amber-900";
  return "bg-zinc-100 text-zinc-600";
}

const statusLabel: Record<string, string> = {
  queued: "в очереди", started: "идёт", finished: "готово", failed: "ошибка",
  canceled: "отменено", scheduled: "запланировано", deferred: "отложено",
};

export function ImportAdmin() {
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [workers, setWorkers] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const pollRef = useRef<number | null>(null);

  const loadJobs = useCallback(async (includeHistory = true) => {
    try {
      const result = await apiFetch<{ items: JobRow[]; history?: JobRow[]; workers?: number }>(
        `/admin/import-jobs?limit=20&include_terminal=${includeHistory ? "true" : "false"}`,
      );
      setJobs([...(result.items || []), ...(result.history || [])].slice(0, 25));
      setWorkers(typeof result.workers === "number" ? result.workers : null);
    } catch {
      // Список задач не критичен: загрузка всё равно работает.
    } finally {
      setJobsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadJobs();
    const onFocus = throttleRefresh(() => void loadJobs());
    window.addEventListener("focus", onFocus);
    return () => {
      window.removeEventListener("focus", onFocus);
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [loadJobs]);

  function patch(name: string, changes: Partial<Upload>) {
    setUploads((rows) => rows.map((row) => (row.name === name ? { ...row, ...changes } : row)));
  }

  async function uploadOne(file: File) {
    const row: Upload = { name: file.name, size: file.size, percent: 0, stage: "upload", detail: "Готовим загрузку…" };
    setUploads((rows) => [...rows, row]);
    const contentType = "application/zip";
    const meta = {
      filename: file.name,
      title: null,
      content_type: contentType,
      size_bytes: file.size,
      last_modified_ms: file.lastModified || null,
    };

    let objectKey = "";
    if (file.size >= CHUNK) {
      patch(file.name, { detail: "Загружаем архив по частям…" });
      const created = await apiFetch<{ object_key: string; upload_id: string }>("/admin/modules/multipart-import-create", {
        method: "POST",
        body: JSON.stringify(meta),
      });
      objectKey = created.object_key;
      const parts: { ETag: string; PartNumber: number }[] = [];
      const total = Math.max(1, Math.ceil(file.size / CHUNK));
      for (let index = 0; index < total; index += 1) {
        const partNumber = index + 1;
        const blob = file.slice(index * CHUNK, Math.min(file.size, (index + 1) * CHUNK));
        const signed = await apiFetch<{ upload_url: string }>("/admin/modules/multipart-import-presign-part", {
          method: "POST",
          body: JSON.stringify({ object_key: objectKey, upload_id: created.upload_id, part_number: partNumber }),
        });
        const base = index * CHUNK;
        const etag = await putFile(signed.upload_url, blob, contentType, (loaded) => {
          patch(file.name, { percent: Math.min(99, Math.round(((base + loaded) / file.size) * 100)) });
        });
        parts.push({ ETag: etag.replace(/"/g, "").trim(), PartNumber: partNumber });
      }
      await apiFetch("/admin/modules/multipart-import-complete", {
        method: "POST",
        body: JSON.stringify({ object_key: objectKey, upload_id: created.upload_id, parts }),
      });
    } else {
      patch(file.name, { detail: "Готовим ссылку на загрузку…" });
      const signed = await apiFetch<{ object_key: string; upload_url: string | null; reused?: boolean; headers?: Record<string, string> | null }>(
        "/admin/modules/presign-import-zip",
        { method: "POST", body: JSON.stringify(meta) },
      );
      objectKey = signed.object_key;
      if (!signed.reused) {
        if (!signed.upload_url) throw new Error("Сервер не выдал ссылку для загрузки");
        await putFile(signed.upload_url, file, contentType, (loaded) => {
          patch(file.name, { percent: Math.min(99, Math.round((loaded / Math.max(1, file.size)) * 100)) });
        }, signed.headers);
      }
    }

    patch(file.name, { percent: 100, stage: "enqueue", detail: "Ставим в очередь на разбор…" });
    const stem = file.name.replace(/\.zip$/i, "").trim();
    const enqueued = await apiFetch<{ job_id?: string }>("/admin/modules/enqueue-import-zip", {
      method: "POST",
      body: JSON.stringify({ object_key: objectKey, title: stem || null, source_filename: file.name, force_reimport: true }),
    });
    patch(file.name, { stage: "done", detail: "Разбор идёт в фоне", jobId: enqueued.job_id });
  }

  async function start(files: File[]) {
    const archives = files.filter((file) => file.name.toLowerCase().endsWith(".zip"));
    if (!archives.length) {
      setError("Нужен ZIP-архив с материалами модуля");
      return;
    }
    setBusy(true);
    setError(null);
    for (const file of archives) {
      try {
        await uploadOne(file);
      } catch (e) {
        patch(file.name, { stage: "failed", detail: e instanceof Error ? e.message : "Не удалось загрузить" });
        setError(e instanceof Error ? e.message : "Не удалось загрузить архив");
      }
    }
    setBusy(false);
    await loadJobs();
    // Опрашиваем очередь ограниченное время: 5 минут хватает, чтобы увидеть итог разбора.
    if (pollRef.current) window.clearInterval(pollRef.current);
    let ticks = 0;
    pollRef.current = window.setInterval(() => {
      ticks += 1;
      void loadJobs();
      if (ticks >= 50 && pollRef.current) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }, 6000);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Импорт и задачи</h2>
          <p className="mt-1.5 text-sm text-zinc-500">
            Новый модуль из ZIP-архива. Существующий модуль обновляется из его редактора — без потери прогресса.
          </p>
        </div>
        <Link href="/admin/modules" className="inline-flex items-center gap-1 text-xs font-medium text-amber-800 hover:underline">
          Вернуться к модулям
        </Link>
      </div>

      {error && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</p>}

      <label className="block cursor-pointer rounded-2xl border-2 border-dashed border-zinc-300 bg-white p-8 text-center transition hover:border-amber-400 hover:bg-amber-50/30">
        <UploadCloud size={30} className="mx-auto mb-3 text-amber-600" />
        <span className="block text-sm font-medium text-zinc-800">Выберите ZIP-архив или перетащите сюда</span>
        <span className="mt-1 block text-xs text-zinc-500">
          Папки верхнего уровня станут каталогами, файлы в корне — уроками, папка <code className="rounded bg-zinc-100 px-1">_module</code> — общими файлами модуля.
          Большие архивы загружаются по частям.
        </span>
        <input ref={inputRef} type="file" accept=".zip,application/zip" multiple className="sr-only" disabled={busy}
          onChange={(event) => {
            const files = Array.from(event.target.files || []);
            event.target.value = "";
            void start(files);
          }} />
        <span className="mt-4 inline-flex items-center gap-2 rounded-xl border-2 border-amber-300/60 bg-white px-4 py-2.5 text-sm font-medium text-zinc-900">
          {busy ? <Loader2 size={16} className="animate-spin" /> : <FileArchive size={16} />}
          {busy ? "Загружаем…" : "Выбрать файл"}
        </span>
      </label>

      {!!uploads.length && (
        <div className="rounded-2xl border border-zinc-200 bg-white shadow-sm">
          <p className="border-b border-zinc-200 p-4 text-sm font-medium">Загрузка</p>
          <div className="divide-y divide-zinc-100">
            {uploads.map((row) => (
              <div key={row.name} className="flex flex-wrap items-center gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-zinc-900">{row.name}</p>
                  <p className="text-xs text-zinc-500">{row.detail}</p>
                  {row.stage === "upload" || row.stage === "enqueue" ? (
                    <div className="mt-2 h-1.5 w-full max-w-sm overflow-hidden rounded bg-zinc-100">
                      <div className="h-full rounded bg-amber-500" style={{ width: `${row.percent}%` }} />
                    </div>
                  ) : null}
                </div>
                <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${row.stage === "failed" ? "bg-rose-50 text-rose-700" : row.stage === "done" || row.stage === "enqueue" ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-900"}`}>
                  {row.stage === "failed" ? "ошибка" : row.stage === "done" ? "в очереди разбора" : row.stage === "enqueue" ? "готово" : `${row.percent}%`}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-2xl border border-zinc-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200 p-4">
          <div>
            <p className="text-sm font-medium">Очередь разбора</p>
            <p className="text-xs text-zinc-500">
              {workers === null ? "Воркер недоступен — задачи будут ждать" : workers > 0 ? `Воркеров активно: ${workers}` : "Воркер импорта не запущен: задачи останутся в очереди"}
            </p>
          </div>
          <Button variant="outline" className={btn} onClick={() => void loadJobs()}><RefreshCw size={16} />Обновить</Button>
        </div>
        {jobsLoading ? (
          <p role="status" className="flex items-center gap-2 p-6 text-sm text-zinc-500"><Loader2 size={16} className="animate-spin" />Загружаем задачи…</p>
        ) : jobs.length ? (
          <div className="divide-y divide-zinc-100">
            {jobs.map((job) => (
              <div key={job.job_id} className="flex flex-wrap items-center gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-zinc-900">{job.module_title || job.filename || "Импорт ZIP"}</p>
                  <p className="text-xs text-zinc-500">
                    {job.stage || job.detail || "—"}
                    {job.created_at ? ` · ${new Date(job.created_at).toLocaleString("ru-RU")}` : ""}
                  </p>
                  {job.error_message && <p className="mt-1 text-xs text-rose-700">{job.error_message}</p>}
                </div>
                <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${statusTone(job.status)}`}>
                  {statusLabel[job.status.toLowerCase()] || job.status}
                </span>
                {job.module_id && (
                  <Link href={`/admin/modules/${job.module_id}`} className="text-xs font-medium text-amber-800 hover:underline">Открыть модуль</Link>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="p-10 text-center text-sm text-zinc-500">
            <CheckCircle2 size={26} className="mx-auto mb-2 text-emerald-600" />
            Задач пока нет. Загрузите ZIP — он появится здесь.
          </div>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-2xl bg-emerald-50 p-4 text-sm leading-6 text-emerald-900">
          <p className="flex items-center gap-2 font-medium"><CheckCircle2 size={16} />Обновление без потери прогресса</p>
          <p className="mt-1 text-emerald-800/80">Файлы и уроки сопоставляются по исходному пути. Уже пройденное остаётся пройденным.</p>
        </div>
        <div className="rounded-2xl bg-amber-50 p-4 text-sm leading-6 text-amber-900">
          <p className="flex items-center gap-2 font-medium"><AlertTriangle size={16} />Если модуль уже существует</p>
          <p className="mt-1 text-amber-800/80">Откройте его редактор → «Обновить из ZIP». Дубликат с тем же названием сервер не создаст.</p>
        </div>
      </div>

      {!!uploads.some((row) => row.stage === "failed") && (
        <p className="flex items-center gap-2 text-xs text-rose-700"><XCircle size={14} />Неудачные загрузки можно повторить: выберите тот же файл ещё раз.</p>
      )}
    </div>
  );
}
