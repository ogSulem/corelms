"use client";

import * as React from "react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { ImportJobItem, RegenJobItem, AdminModuleItem } from "../adminpanel-client";

interface ImportTabProps {
  importFiles: File[];
  importInputRef: React.RefObject<HTMLInputElement | null>;
  setImportFiles: (files: File[]) => void;
  importStageLabel: string;
  s3UploadProgress?: {
    loaded: number;
    total: number;
    speedBps: number;
    etaSeconds: number | null;
    percent: number;
  } | null;
  importPendingCount?: number;
  importPendingNames?: string[];
  importEnqueueProgress: { total: number; done: number } | null;
  importBatch: { total: number; done: number } | null;
  importBusy: boolean;
  startImport: () => void;
  importQueue: ImportJobItem[];
  importQueueLoading: boolean;
  loadImportQueue: (limit?: number, includeTerminal?: boolean) => Promise<void>;
  setImportQueueView: (view: "active" | "history") => void;
  setImportQueueModalOpen: (open: boolean) => void;
  importQueueModalOpen: boolean;
  importQueueView: "active" | "history";
  importQueueHistory: ImportJobItem[];
  setSelectedJobId: (id: string) => void;
  setJobPanelOpen: (open: boolean) => void;
  cancelImportJob: (id: string) => void;
  cancelRegenJob: (id: string) => void;
  retryImportJob: (id: string) => void;
  openModuleFromImport: (it: ImportJobItem) => void;
  regenQueue: RegenJobItem[];
  regenHistoryLoading: boolean;
  loadRegenHistory: () => Promise<void>;
  setRegenQueueModalOpen: (open: boolean) => void;
  regenQueueModalOpen: boolean;
  regenHistory: any[];
  jobPanelOpen: boolean;
  selectedJobId: string;
  jobStatus: string;
  jobStage: string;
  importJobStageLabel: string;
  copy: (text: string) => void;
  cancelCurrentJob: () => void;
  cancelBusy: boolean;
  jobKind: string;
  jobModuleTitle: string;
  jobDetail: string;
  jobError: string;
  jobErrorCode: string;
  jobErrorHint: string;
  clientImportStage: string;
  clientImportFileName: string;
  selectedAdminModule: AdminModuleItem | null;
  selectedAdminModuleQuality: {
    ai_current: number;
    heur_current: number;
    total_current: number;
    fallback_current: number;
    needs_regen_current: number;
  };
  jobResult: any;
}

export default function ImportTab(props: ImportTabProps) {
  const {
    importFiles,
    importInputRef,
    setImportFiles,
    importStageLabel,
    s3UploadProgress,
    importPendingCount,
    importPendingNames,
    importEnqueueProgress,
    importBatch,
    importBusy,
    startImport,
    importQueue,
    importQueueLoading,
    loadImportQueue,
    setImportQueueView,
    setImportQueueModalOpen,
    importQueueModalOpen,
    importQueueView,
    importQueueHistory,
    setSelectedJobId,
    setJobPanelOpen,
    cancelImportJob,
    cancelRegenJob,
    retryImportJob,
    openModuleFromImport,
    regenQueue,
    regenHistoryLoading,
    loadRegenHistory,
    regenHistory,
    jobPanelOpen,
    selectedJobId,
    jobStatus,
    jobStage,
    importJobStageLabel,
    copy,
    cancelCurrentJob,
    cancelBusy,
    jobKind,
    jobModuleTitle,
    jobDetail,
    jobError,
    jobErrorCode,
    jobErrorHint,
    clientImportStage,
    clientImportFileName,
    selectedAdminModule,
    selectedAdminModuleQuality,
    jobResult,
  } = props;

  const s3Label = useMemo(() => {
    const p = s3UploadProgress;
    if (!p) return null;
    const humanBytes = (n: number): string => {
      const v = Math.max(0, Number(n || 0));
      const units = ["B", "KB", "MB", "GB"];
      let x = v;
      let i = 0;
      while (x >= 1024 && i < units.length - 1) {
        x /= 1024;
        i++;
      }
      const digits = i <= 1 ? 0 : 1;
      return `${x.toFixed(digits)} ${units[i]}`;
    };

    const humanSpeed = (bps: number): string => {
      const v = Math.max(0, Number(bps || 0));
      if (v < 1) return "—";
      if (v < 1024 * 1024) return `${Math.round(v / 1024)} KB/s`;
      return `${(v / (1024 * 1024)).toFixed(1)} MB/s`;
    };

    const speed = humanSpeed(p.speedBps);
    const eta = typeof p.etaSeconds === "number" ? `${p.etaSeconds}s` : "—";
    return {
      percent: p.percent,
      loadedHuman: humanBytes(p.loaded),
      totalHuman: humanBytes(p.total),
      speed,
      eta,
    };
  }, [s3UploadProgress]);

  type PipelineKind = "import" | "regen";
  type PipelineItem = {
    kind: PipelineKind;
    job_id: string;
    title: string;
    created_at?: string;
    status?: string;
    stage?: string;
    detail?: string;
    error?: string | null;
    error_code?: string;
    error_hint?: string;
    error_message?: string;
    module_id?: string;
    module_title?: string;
    submodule_id?: string;
    submodule_title?: string;
    object_key?: string;
    source_filename?: string;
  };

  const pipelineActive = useMemo(() => {
    const out: PipelineItem[] = [];
    for (const it of importQueue || []) {
      out.push({
        kind: "import",
        job_id: String(it.job_id),
        title: String(it.module_title || it.title || it.source_filename || "ZIP"),
        created_at: it.created_at,
        status: it.status,
        stage: it.stage,
        detail: it.detail,
        error: it.error,
        error_code: it.error_code,
        error_hint: it.error_hint,
        error_message: it.error_message,
        module_id: it.module_id,
        module_title: it.module_title,
        object_key: it.object_key,
        source_filename: it.source_filename,
      });
    }
    for (const it of regenQueue || []) {
      out.push({
        kind: "regen",
        job_id: String(it.job_id),
        title: String(
          it.submodule_title
            ? `УРОК: ${String(it.submodule_title || "").trim()}`
            : it.module_title || it.module_id || "МОДУЛЬ"
        ),
        created_at: it.created_at,
        status: it.status,
        stage: it.stage,
        detail: it.detail,
        error: it.error,
        error_code: it.error_code,
        error_hint: it.error_hint,
        error_message: it.error_message,
        module_id: it.module_id,
        module_title: it.module_title,
        submodule_id: (it as any).submodule_id,
        submodule_title: (it as any).submodule_title,
      });
    }

    const score = (s?: string) => {
      const v = String(s || "").trim();
      if (!v) return 0;
      const t = Date.parse(v);
      return Number.isFinite(t) ? t : 0;
    };
    out.sort((a, b) => score(b.created_at) - score(a.created_at));
    return out;
  }, [importQueue, regenQueue]);

  const pipelineHistory = useMemo(() => {
    const out: PipelineItem[] = [];
    for (const it of importQueueHistory || []) {
      out.push({
        kind: "import",
        job_id: String(it.job_id),
        title: String(it.module_title || it.title || it.source_filename || "ZIP"),
        created_at: it.created_at,
        status: it.status,
        stage: it.stage,
        detail: it.detail,
        error: it.error,
        error_code: it.error_code,
        error_hint: it.error_hint,
        error_message: it.error_message,
        module_id: it.module_id,
        module_title: it.module_title,
        object_key: it.object_key,
        source_filename: it.source_filename,
      });
    }
    for (const it of regenHistory || []) {
      const jid = String((it as any)?.job_id || (it as any)?.id || "").trim();
      if (!jid) continue;
      const subTitle = String((it as any)?.submodule_title || "").trim();
      out.push({
        kind: "regen",
        job_id: jid,
        title: String(subTitle ? `УРОК: ${subTitle}` : (it as any)?.module_title || (it as any)?.module_id || "МОДУЛЬ"),
        created_at: String((it as any)?.created_at || "") || undefined,
        status: String((it as any)?.status || "") || undefined,
        stage: String((it as any)?.stage || "") || undefined,
        detail: String((it as any)?.detail || "") || undefined,
        error: (it as any)?.error ?? null,
        error_code: String((it as any)?.error_code || "") || undefined,
        error_hint: String((it as any)?.error_hint || "") || undefined,
        error_message: String((it as any)?.error_message || "") || undefined,
        module_id: String((it as any)?.module_id || "") || undefined,
        module_title: String((it as any)?.module_title || "") || undefined,
        submodule_id: String((it as any)?.submodule_id || "") || undefined,
        submodule_title: subTitle || undefined,
      });
    }

    const score = (s?: string) => {
      const v = String(s || "").trim();
      if (!v) return 0;
      const t = Date.parse(v);
      return Number.isFinite(t) ? t : 0;
    };
    out.sort((a, b) => score(b.created_at) - score(a.created_at));
    return out;
  }, [importQueueHistory, regenHistory]);

  const badgeFor = (it: PipelineItem) => {
    const st = String(it.status || "").toLowerCase();
    const stage = String(it.stage || "").toLowerCase();
    if (st === "finished") return "ГОТОВО";
    if (st === "failed") return "ОШИБКА";
    if (stage === "canceled" || st === "canceled") return "ОТМЕНЕНО";
    if (st === "queued" || st === "deferred") return "В ОЧЕРЕДИ";
    if (st === "started") return "В РАБОТЕ";
    return (st || "—").toUpperCase();
  };

  const progressForImport = (it: PipelineItem): number | null => {
    if (it.kind !== "import") return null;
    const st = String(it.status || "").trim().toLowerCase();
    const stage = String(it.stage || "").trim().toLowerCase();
    if (st === "finished") return 100;
    if (st === "failed" || st === "canceled" || stage === "canceled") return 100;
    if (stage === "upload_s3") return Math.max(1, Math.min(99, Number(s3Label?.percent || 1)));

    // backend pipeline stages (module_import_jobs)
    if (stage === "enqueue") return 12;
    if (stage === "queued" || stage === "deferred" || st === "queued" || st === "deferred") return 8;
    if (stage === "start" || stage === "load") return 18;
    if (stage === "download") return 28;
    if (stage === "extract") return 38;
    if (stage === "import") return 55;
    if (stage === "ai" || stage === "ollama") return 70;
    if (stage === "fallback") return 74;
    if (stage === "replace") return 80;
    if (stage === "commit") return 90;
    if (stage === "cleanup") return 96;
    if (stage === "regen_enqueue" || stage === "regen_enqueued" || stage === "finalizing") return 98;

    if (st === "started") return 45;
    return 30;
  };

  const canCancelImport = (it: { status?: string } | null | undefined) => {
    const st = String((it as any)?.status || "").trim().toLowerCase();
    if (!st) return false;
    return st === "queued" || st === "deferred" || st === "scheduled";
  };

  const [uploadOverlayMinimized, setUploadOverlayMinimized] = useState(false);

  const uploadActive = (() => {
    if (!importBusy) return false;
    const st = String(clientImportStage || "").trim().toLowerCase();
    if (!st) return false;
    return st !== "processing" && st !== "done" && st !== "failed" && st !== "canceled";
  })();

  return (
    <div className="mt-8 space-y-6">
      <Modal
        open={uploadActive && !uploadOverlayMinimized}
        title="ИДЁТ ЗАГРУЗКА"
        disableClose
        onClose={() => {
          // non-closable by design
        }}
        className="max-w-[min(96vw,720px)]"
        footer={
          <div className="flex items-center justify-between gap-3">
            <div className="text-[10px] font-bold text-zinc-600">Можно свернуть, но не обновляй страницу.</div>
            <button
              type="button"
              className="h-10 rounded-xl px-4 text-[10px] font-black uppercase tracking-widest transition border border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50"
              onClick={() => setUploadOverlayMinimized(true)}
            >
              СВЕРНУТЬ
            </button>
          </div>
        }
      >
        <div className="space-y-3">
          <div className="text-[11px] font-bold text-zinc-900">
            Не обновляй страницу и не закрывай вкладку — иначе файл потеряется.
          </div>
          {String(clientImportFileName || "").trim() ? (
            <div className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[11px] font-bold text-zinc-700 break-words">
              {String(clientImportFileName || "").trim()}
            </div>
          ) : null}

          {String(clientImportStage || "")
            .trim()
            .toLowerCase() === "upload_s3" && s3Label ? (
            <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-700">STORAGE UPLOAD</div>
                <div className="text-[10px] font-black tabular-nums text-zinc-900">{s3Label.percent}%</div>
              </div>
              <div className="mt-2 h-2 w-full rounded-full bg-white border border-zinc-200 overflow-hidden">
                <div className="h-full bg-[#fe9900] transition-all" style={{ width: `${s3Label.percent}%` }} />
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] font-black uppercase tracking-widest text-zinc-600">
                <div className="rounded-full border border-zinc-200 bg-white px-2.5 py-1">
                  {s3Label.loadedHuman} / {s3Label.totalHuman}
                </div>
                <div className="rounded-full border border-zinc-200 bg-white px-2.5 py-1">{s3Label.speed}</div>
                <div className="rounded-full border border-zinc-200 bg-white px-2.5 py-1">ОСТАЛОСЬ ~ {s3Label.eta}</div>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3">
              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-700">ОБРАБОТКА</div>
              <div className="mt-2 text-[11px] font-bold text-zinc-700">
                {String(importStageLabel || "").trim() || "..."}
              </div>
            </div>
          )}
        </div>
      </Modal>

      {uploadActive ? (
        <div className="rounded-2xl border border-zinc-200 bg-white p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ЗАГРУЗКА В STORAGE</div>
              {String(clientImportFileName || "").trim() ? (
                <div className="mt-1 text-[11px] font-bold text-zinc-800 break-words">{String(clientImportFileName || "").trim()}</div>
              ) : null}
            </div>
            {uploadOverlayMinimized ? (
              <button
                type="button"
                className="h-9 rounded-xl px-3 text-[9px] font-black uppercase tracking-widest transition border border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50"
                onClick={() => setUploadOverlayMinimized(false)}
              >
                РАЗВЕРНУТЬ
              </button>
            ) : null}
          </div>

          {String(clientImportStage || "").trim().toLowerCase() === "upload_s3" && s3Label ? (
            <div className="mt-3">
              <div className="mt-2 h-2 w-full rounded-full bg-white border border-zinc-200 overflow-hidden">
                <div className="h-full bg-[#fe9900] transition-all" style={{ width: `${s3Label.percent}%` }} />
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] font-black uppercase tracking-widest text-zinc-600">
                <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1">{s3Label.loadedHuman} / {s3Label.totalHuman}</div>
                <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1">{s3Label.speed}</div>
                <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1">ОСТАЛОСЬ ~ {s3Label.eta}</div>
              </div>
            </div>
          ) : (
            <div className="mt-2 text-[11px] font-bold text-zinc-700">{String(importStageLabel || "").trim() || "..."}</div>
          )}
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-12 items-start">
        <div className="lg:col-span-7 relative overflow-hidden rounded-[22px] border border-zinc-200 bg-white/70 backdrop-blur-md p-3 shadow-2xl shadow-zinc-950/10">
          <div className="flex flex-wrap items-center gap-3 justify-between">
            <div className="min-w-[220px]">
              <div className="text-[9px] font-black uppercase tracking-[0.28em] text-zinc-500">
                ИМПОРТ
                <span className="ml-3 text-[9px] font-black uppercase tracking-widest text-zinc-400">
                  {importFiles.length ? `ФАЙЛОВ: ${importFiles.length}` : "ФАЙЛЫ НЕ ВЫБРАНЫ"}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <input
                  ref={importInputRef}
                  type="file"
                  accept=".zip"
                  multiple
                  className="hidden"
                  onChange={(e) => setImportFiles(Array.from(e.target.files || []))}
                />
                <button
                  type="button"
                  className="h-8 rounded-xl border border-zinc-200 bg-white px-3 text-[9px] font-black uppercase tracking-widest text-zinc-800 hover:bg-zinc-50"
                  onClick={() => importInputRef.current?.click()}
                >
                  Выбрать ZIP
                </button>
                {importFiles.length ? (
                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-600">
                    {importFiles.length === 1 ? String(importFiles[0]?.name || "") : `Выбрано: ${importFiles.length}`}
                  </div>
                ) : null}
              </div>
            </div>

            <div className="flex items-center gap-2">
              <div className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-600">
                {importStageLabel}
              </div>
              <Button
                variant="primary"
                className="h-8 rounded-xl font-black uppercase tracking-widest text-[9px]"
                disabled={importFiles.length === 0}
                onClick={() => void startImport()}
              >
                {importBusy ? "..." : "ЗАПУСТИТЬ"}
              </Button>
            </div>
          </div>

          <div className="mt-3 rounded-2xl border border-zinc-200 bg-white p-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">
                ИМПОРТ → РЕГЕН (ЕДИНАЯ ОЧЕРЕДЬ)
                <span className="ml-3 text-[9px] font-black uppercase tracking-widest text-zinc-400">
                  {importQueueLoading || regenHistoryLoading ? "..." : `ЗАДАЧ: ${pipelineActive.length}`}
                </span>
              </div>

              {typeof importPendingCount === "number" && importPendingCount > 0 ? (
                <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                  ОЧЕРЕДЬ ИМПОРТА: {importPendingCount}
                </div>
              ) : null}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                  onClick={() => {
                    void loadImportQueue(20, false);
                    void loadRegenHistory();
                  }}
                  disabled={importQueueLoading || regenHistoryLoading}
                >
                  {importQueueLoading || regenHistoryLoading ? "..." : "ОБНОВИТЬ"}
                </button>
                <button
                  type="button"
                  className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                  onClick={() => {
                    setImportQueueView("active");
                    setImportQueueModalOpen(true);
                    void loadImportQueue(50, true);
                    void loadRegenHistory();
                  }}
                >
                  ИСТОРИЯ / ДЕТАЛИ
                </button>
              </div>
            </div>

            {String(clientImportStage || "").trim().toLowerCase() === "upload_s3" && s3Label ? (
              <div className="mt-3 rounded-xl border border-zinc-200 bg-zinc-50 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-700">STORAGE UPLOAD</div>
                  <div className="text-[10px] font-black tabular-nums text-zinc-900">{s3Label.percent}%</div>
                </div>
                {String(clientImportFileName || "").trim() ? (
                  <div className="mt-1 text-[10px] font-bold text-zinc-700 break-words">{String(clientImportFileName || "").trim()}</div>
                ) : null}
                <div className="mt-2 h-2 w-full rounded-full bg-white border border-zinc-200 overflow-hidden">
                  <div className="h-full bg-[#fe9900] transition-all" style={{ width: `${s3Label.percent}%` }} />
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] font-black uppercase tracking-widest text-zinc-600">
                  <div className="rounded-full border border-zinc-200 bg-white px-2.5 py-1">{s3Label.loadedHuman} / {s3Label.totalHuman}</div>
                  <div className="rounded-full border border-zinc-200 bg-white px-2.5 py-1">{s3Label.speed}</div>
                  <div className="rounded-full border border-zinc-200 bg-white px-2.5 py-1">ОСТАЛОСЬ ~ {s3Label.eta}</div>
                </div>
              </div>
            ) : null}

            {Array.isArray(importPendingNames) && importPendingNames.length ? (
              <div className="mt-3 rounded-xl border border-zinc-200 bg-white p-3">
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">В ОЧЕРЕДИ (ЛОКАЛЬНО)</div>
                <div className="mt-2 grid gap-2">
                  {importPendingNames.slice(0, 5).map((n, idx) => (
                    <div key={`${idx}:${n}`} className="rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 text-[10px] font-bold text-zinc-800 break-words">
                      {String(n || "").trim()}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="mt-3 grid gap-2">
              {(() => {
                const imports = (pipelineActive || []).filter((x: PipelineItem) => x.kind === "import");
                const regens = (pipelineActive || []).filter((x: PipelineItem) => x.kind === "regen");
                return (
                  <>
                    {imports.slice(0, 3).length ? (
                      <div className="grid gap-2">
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ИМПОРТЫ (АКТИВНЫЕ)</div>
                        {imports.map((it: PipelineItem) => {
                          const stage = String(it.stage || "").toLowerCase();
                          const st = String(it.status || "").toLowerCase();
                          const terminal = st === "finished" || st === "failed" || stage === "canceled" || st === "canceled";
                          const createdAt = String(it.created_at || "").trim();
                          const detail = String(it.detail || "").trim();
                          const badge = badgeFor(it);
                          const pct = progressForImport(it);
                          return (
                            <button
                              key={`${it.kind}:${it.job_id}`}
                              type="button"
                              className="w-full text-left rounded-xl border border-zinc-200 bg-white px-3 py-2 hover:bg-zinc-50"
                              onClick={() => {
                                setSelectedJobId(String(it.job_id));
                                setJobPanelOpen(true);
                              }}
                            >
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <div className="truncate text-[10px] font-black uppercase tracking-widest text-zinc-900">{it.title}</div>
                                  <div className="mt-1 flex flex-wrap items-center gap-2">
                                    <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                      IMPORT · {badge}
                                    </div>
                                    <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                      {stage ? stage.toUpperCase() : "—"}
                                    </div>
                                    {createdAt ? (
                                      <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                        {createdAt.replace("T", " ").slice(0, 16)}
                                      </div>
                                    ) : null}
                                  </div>
                                  {typeof pct === "number" ? (
                                    <div className="mt-2 h-2 w-full rounded-full bg-white border border-zinc-200 overflow-hidden">
                                      <div className="h-full bg-[#fe9900] transition-all" style={{ width: `${Math.max(1, Math.min(100, pct))}%` }} />
                                    </div>
                                  ) : null}
                                  {detail ? (
                                    <div className="mt-1 text-[10px] font-bold text-zinc-600 break-words line-clamp-2">{detail}</div>
                                  ) : null}
                                </div>
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    ) : null}

                    {regens.length ? (
                      <div className="grid gap-2">
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">РЕГЕН (АКТИВНЫЕ)</div>
                        {regens.map((it: PipelineItem) => {
                          const stage = String(it.stage || "").toLowerCase();
                          const st = String(it.status || "").toLowerCase();
                          const terminal = st === "finished" || st === "failed" || stage === "canceled" || st === "canceled";
                          const createdAt = String(it.created_at || "").trim();
                          const detail = String(it.detail || "").trim();
                          const badge = badgeFor(it);
                          return (
                            <button
                              key={`${it.kind}:${it.job_id}`}
                              type="button"
                              className="w-full text-left flex items-center justify-between gap-3 rounded-xl border border-zinc-200 bg-white px-3 py-2 hover:bg-zinc-50"
                              onClick={() => {
                                setSelectedJobId(String(it.job_id));
                                setJobPanelOpen(true);
                              }}
                            >
                              <div className="min-w-0">
                                <div className="truncate text-[10px] font-black uppercase tracking-widest text-zinc-900">{it.title}</div>
                                <div className="mt-1 flex flex-wrap items-center gap-2">
                                  <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                    {it.kind === "import" ? "IMPORT" : "REGEN"} · {badge}
                                  </div>
                                  {String(it.submodule_title || "").trim() ? (
                                    <div className="rounded-full border border-[#fe9900]/25 bg-[#fe9900]/10 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-[#fe9900]">
                                      УРОК
                                    </div>
                                  ) : null}
                                  <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                    {stage ? stage.toUpperCase() : "—"}
                                  </div>
                                  {createdAt ? (
                                    <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                      {createdAt.replace("T", " ").slice(0, 16)}
                                    </div>
                                  ) : null}
                                </div>
                                {detail ? (
                                  <div className="mt-1 text-[10px] font-bold text-zinc-600 break-words line-clamp-2">{detail}</div>
                                ) : null}
                              </div>

                              <div className="shrink-0 flex items-center gap-2">
                                <button
                                  type="button"
                                  className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[9px] font-black uppercase tracking-widest text-rose-800 hover:bg-rose-100"
                                  disabled={terminal}
                                  onClick={(e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    void cancelRegenJob(String(it.job_id));
                                  }}
                                >
                                  ОТМЕНА
                                </button>
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    ) : null}
                  </>
                );
              })()}

              {!importQueueLoading && !regenHistoryLoading && !(pipelineActive || []).length ? (
                <div className="text-[10px] font-bold text-zinc-500">—</div>
              ) : null}
            </div>
          </div>

          <Modal
            open={importQueueModalOpen}
            onClose={() => setImportQueueModalOpen(false)}
            title="ИМПОРТ → РЕГЕН: ОЧЕРЕДЬ И ИСТОРИЯ"
            className="max-w-[min(96vw,1200px)]"
          >
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600">
                  {importQueueView === "history" ? "ИСТОРИЯ" : "АКТИВНЫЕ"}
                  <span className="ml-2 text-zinc-400">
                    {importQueueLoading || regenHistoryLoading
                      ? "..."
                      : importQueueView === "history"
                        ? pipelineHistory.length
                        : pipelineActive.length}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant={importQueueView === "active" ? "primary" : "outline"}
                    className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                    onClick={() => setImportQueueView("active")}
                  >
                    АКТИВНЫЕ
                  </Button>
                  <Button
                    variant={importQueueView === "history" ? "primary" : "outline"}
                    className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                    onClick={() => setImportQueueView("history")}
                  >
                    ИСТОРИЯ
                  </Button>
                  <Button
                    variant="outline"
                    className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                    onClick={() => {
                      void loadImportQueue(50, true);
                      void loadRegenHistory();
                    }}
                  >
                    ОБНОВИТЬ
                  </Button>
                </div>
              </div>

              <div className="max-h-[72vh] overflow-auto pr-1 grid gap-2">
                {(importQueueView === "history" ? pipelineHistory : pipelineActive).map((it: PipelineItem) => {
                  const st = String(it.status || "").toLowerCase();
                  const stage = String(it.stage || "").toLowerCase();
                  const terminal = st === "finished" || st === "failed" || stage === "canceled" || st === "canceled";
                  const label = String(it.title || "");
                  const badge = badgeFor(it);
                  return (
                    <button
                      key={`${it.kind}:${it.job_id}`}
                      type="button"
                      className="w-full text-left rounded-xl border border-zinc-200 bg-white p-3 hover:bg-zinc-50"
                      onClick={() => {
                        setSelectedJobId(String(it.job_id));
                        setJobPanelOpen(true);
                        setImportQueueModalOpen(false);
                      }}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-[10px] font-black uppercase tracking-widest text-zinc-900">{label}</div>
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                              {it.kind === "import" ? "IMPORT" : "REGEN"}
                            </div>
                            <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                              {badge}
                            </div>
                            {String(it.created_at || "").trim() ? (
                              <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                {String(it.created_at || "").replace("T", " ").slice(0, 16)}
                              </div>
                            ) : null}
                            {String(it.stage || "").trim() ? (
                              <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                {String(it.stage || "").toUpperCase()}
                              </div>
                            ) : null}
                            {String(it.detail || "").trim() ? (
                              <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700 truncate max-w-[420px]">
                                {String(it.detail || "").trim()}
                              </div>
                            ) : null}
                          </div>
                        </div>

                        <div className="shrink-0 flex items-center gap-2">
                          {it.kind === "import" && st === "finished" && String(it?.module_id || "").trim() ? (
                            <Button
                              variant="primary"
                              className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                openModuleFromImport(it as any);
                              }}
                            >
                              МОДУЛЬ
                            </Button>
                          ) : null}
                          {it.kind === "regen" ? (
                            <Button
                              variant="destructive"
                              className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                              disabled={terminal}
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                void cancelRegenJob(String(it.job_id));
                              }}
                            >
                              ОТМЕНА
                            </Button>
                          ) : null}
                        </div>
                      </div>

                      {it.error ? (
                        <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-[10px] font-bold text-rose-800 break-words">
                          {it.error_hint ? `${it.error_hint}\n` : ""}
                          {it.error_code ? `CODE: ${it.error_code}\n` : ""}
                          {it.error}
                        </div>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            </div>
          </Modal>
        </div>

        <div className="lg:col-span-5">
          <div className="relative overflow-hidden rounded-[22px] border border-zinc-200 bg-white/70 backdrop-blur-md p-3 shadow-2xl shadow-zinc-950/10">
            <div className="rounded-2xl border border-zinc-200 bg-white p-3">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ЗАДАЧА</div>
                  <div className="mt-1 truncate text-[11px] font-black text-zinc-950">{selectedJobId || "—"}</div>
                  {jobKind || jobModuleTitle ? (
                    <div className="mt-1 text-[10px] font-bold text-zinc-600 break-words">
                      {jobKind ? `ТИП: ${String(jobKind || "").toUpperCase()}` : ""}
                      {jobModuleTitle ? `${jobKind ? " · " : ""}${jobModuleTitle}` : ""}
                    </div>
                  ) : null}
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                      {(jobStatus || "—").toUpperCase()}
                    </div>
                    <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                      {(importJobStageLabel || jobStage || "—").toString()}
                    </div>
                  </div>
                </div>

                <div className="shrink-0 flex items-center gap-2">
                  <button
                    type="button"
                    className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                    disabled={!selectedJobId}
                    onClick={() => void copy(selectedJobId)}
                  >
                    КОПИРОВАТЬ
                  </button>
                  <button
                    type="button"
                    className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[9px] font-black uppercase tracking-widest text-rose-800 hover:bg-rose-100 disabled:opacity-60"
                    disabled={
                      String(jobKind || "").trim().toLowerCase() !== "regen" ||
                      cancelBusy ||
                      String(jobStatus || "").trim().toLowerCase() === "missing" ||
                      String(jobStatus || "").trim().toLowerCase() === "finished" ||
                      String(jobStatus || "").trim().toLowerCase() === "failed" ||
                      String(jobStage || "").trim().toLowerCase() === "canceled"
                    }
                    onClick={() => void cancelCurrentJob()}
                  >
                    {cancelBusy ? "..." : "ОТМЕНА"}
                  </button>
                </div>
              </div>

              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ДЕТАЛЬ</div>
                  <div className="mt-2 text-[11px] font-bold text-zinc-950 break-words max-h-[84px] overflow-auto pr-1">
                    {jobDetail || "—"}
                  </div>
                </div>
                <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ОШИБКА</div>
                  {String(jobStatus || "").trim().toLowerCase() === "missing" ? (
                    <div className="mt-2 rounded-xl border border-zinc-200 bg-zinc-50 p-3 text-[10px] font-bold text-zinc-700 break-words max-h-[84px] overflow-auto pr-1">
                      {jobErrorHint ? `${jobErrorHint}\n` : ""}
                      {jobErrorCode ? `CODE: ${jobErrorCode}\n` : ""}
                      {jobError || "job not found"}
                    </div>
                  ) : jobError ? (
                    <div className="mt-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-[10px] font-bold text-rose-800 break-words max-h-[84px] overflow-auto pr-1">
                      {jobErrorHint ? `${jobErrorHint}\n` : ""}
                      {jobErrorCode ? `CODE: ${jobErrorCode}\n` : ""}
                      {jobError}
                    </div>
                  ) : (
                    <div className="mt-2 text-[11px] font-bold text-zinc-500">—</div>
                  )}
                </div>
              </div>
            </div>

            <div className="mt-3 rounded-2xl border border-zinc-200 bg-white p-3">
              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">РЕЗУЛЬТАТ</div>
              {jobStatus === "finished" && jobResult && typeof jobResult === "object" ? (
                <div className="mt-3 space-y-3">
                  {String(jobKind || "").toLowerCase() === "import" ? (
                    <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ИТОГ ИМПОРТА</div>
                      <div className="mt-2 grid gap-2">
                        <div className="text-[11px] font-bold text-zinc-950 break-words">
                          МОДУЛЬ: {String((jobResult as any)?.report?.module_title || (jobResult as any)?.module_id || "—")}
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          {String((jobResult as any)?.module_id || "").trim() ? (
                            <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                              module_id: {String((jobResult as any)?.module_id).slice(0, 10)}
                            </div>
                          ) : null}
                          {String((jobResult as any)?.regen_job_id || "").trim() ? (
                            <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                              regen_job: {String((jobResult as any)?.regen_job_id).slice(0, 10)}
                            </div>
                          ) : null}
                          {typeof (jobResult as any)?.report?.lessons === "number" ? (
                            <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                              уроков: {String((jobResult as any)?.report?.lessons)}
                            </div>
                          ) : null}
                        </div>

                        {String((jobResult as any)?.module_id || "").trim() ? (
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            <Button
                              variant="primary"
                              className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                              onClick={() => {
                                const mid = String((jobResult as any)?.module_id || "").trim();
                                if (!mid) return;
                                window.location.href = `/modules/${encodeURIComponent(mid)}`;
                              }}
                            >
                              ОТКРЫТЬ МОДУЛЬ
                            </Button>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  ) : null}

                  {String(jobKind || "").toLowerCase() === "regen" ? (
                    <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ИТОГ РЕГЕНА</div>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        {typeof (jobResult as any)?.questions_total === "number" ? (
                          <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                            всего: {String((jobResult as any)?.questions_total)}
                          </div>
                        ) : null}
                        {typeof (jobResult as any)?.questions_ai === "number" ? (
                          <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                            ai: {String((jobResult as any)?.questions_ai)}
                          </div>
                        ) : null}
                        {typeof (jobResult as any)?.questions_heur === "number" ? (
                          <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                            heur: {String((jobResult as any)?.questions_heur)}
                          </div>
                        ) : null}
                        {typeof (jobResult as any)?.questions_fallback === "number" ? (
                          <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                            fallback: {String((jobResult as any)?.questions_fallback)}
                          </div>
                        ) : null}
                        {typeof (jobResult as any)?.needs_regen_db === "number" ? (
                          <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                            needs_regen: {String((jobResult as any)?.needs_regen_db)}
                          </div>
                        ) : null}
                      </div>

                      {String((jobResult as any)?.last_ai_error || "").trim() ? (
                        <div className="mt-3 rounded-xl border border-zinc-200 bg-zinc-50 p-3 text-[10px] font-bold text-zinc-700 break-words">
                          LAST_AI_ERROR: {String((jobResult as any)?.last_ai_error || "")}
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  <details className="rounded-2xl border border-zinc-200 bg-white p-4">
                    <summary className="cursor-pointer text-[9px] font-black uppercase tracking-widest text-zinc-600">
                      RAW JSON
                    </summary>
                    <div className="mt-3 overflow-hidden rounded-xl border border-zinc-100 bg-white/50 p-3">
                      <pre className="text-[9px] font-mono text-zinc-600 whitespace-pre-wrap break-words overflow-x-hidden max-h-[420px] overflow-y-auto">
                        {JSON.stringify(jobResult, null, 2)}
                      </pre>
                    </div>
                  </details>
                </div>
              ) : (
                <div className="mt-2 text-[11px] font-bold text-zinc-500">—</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
