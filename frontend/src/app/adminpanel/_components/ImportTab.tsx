"use client";

import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { ImportJobItem, RegenJobItem, AdminModuleItem } from "../adminpanel-client";

interface ImportTabProps {
  importFiles: File[];
  importInputRef: React.RefObject<HTMLInputElement | null>;
  setImportFiles: (files: File[]) => void;
  importStageLabel: string;
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

export function ImportTab(props: ImportTabProps) {
  const {
    importFiles,
    importInputRef,
    setImportFiles,
    importStageLabel,
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
        title: String(it.module_title || it.module_id || "МОДУЛЬ"),
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
      out.push({
        kind: "regen",
        job_id: jid,
        title: String((it as any)?.module_title || (it as any)?.module_id || "МОДУЛЬ"),
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

  return (
    <div className="mt-8 space-y-6">
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
              {importEnqueueProgress ? (
                <div className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 tabular-nums">
                  {importEnqueueProgress.done}/{importEnqueueProgress.total}
                </div>
              ) : null}
              {importBatch ? (
                <div className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 tabular-nums">
                  {importBatch.done}/{importBatch.total}
                </div>
              ) : null}
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

            <div className="mt-3 rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 text-[10px] font-bold text-zinc-700">
              Импорт загружает ZIP в хранилище и быстро добавляет модуль. Затем автоматически запускается реген тестов (нейросеть).
              Выполнение идёт в worker (RQ), статус обновляется здесь по задачам.
            </div>

            <div className="mt-3 grid gap-2">
              {(pipelineActive || []).slice(0, 6).map((it) => {
                const stage = String(it.stage || "").toLowerCase();
                const st = String(it.status || "").toLowerCase();
                const terminal = st === "finished" || st === "failed" || stage === "canceled" || st === "canceled";
                const createdAt = String(it.created_at || "").trim();
                const detail = String(it.detail || "").trim();
                const badge = badgeFor(it);
                return (
                  <div key={`${it.kind}:${it.job_id}`} className="flex items-center justify-between gap-3 rounded-xl border border-zinc-200 bg-white px-3 py-2">
                    <div className="min-w-0">
                      <div className="truncate text-[10px] font-black uppercase tracking-widest text-zinc-900">{it.title}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                          {it.kind === "import" ? "IMPORT" : "REGEN"}
                        </div>
                        <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                          {badge}
                        </div>
                        <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                          {stage ? stage.toUpperCase() : "—"}
                        </div>
                        {createdAt ? (
                          <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                            {createdAt.replace("T", " ").slice(0, 16)}
                          </div>
                        ) : null}
                        {detail ? (
                          <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700 truncate max-w-[260px]">
                            {detail}
                          </div>
                        ) : null}
                      </div>
                    </div>

                    <div className="shrink-0 flex items-center gap-2">
                      <button
                        type="button"
                        className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                        onClick={() => {
                          setSelectedJobId(String(it.job_id));
                          setJobPanelOpen(true);
                        }}
                      >
                        ОТКРЫТЬ
                      </button>
                      {it.kind === "regen" ? (
                        <button
                          type="button"
                          className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[9px] font-black uppercase tracking-widest text-rose-800 hover:bg-rose-100"
                          disabled={terminal}
                          onClick={() => void cancelImportJob(String(it.job_id))}
                        >
                          ОТМЕНА
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
              {!importQueueLoading && !regenHistoryLoading && !(pipelineActive || []).length ? (
                <div className="text-[10px] font-bold text-zinc-500">—</div>
              ) : null}
            </div>
          </div>

          <Modal open={importQueueModalOpen} onClose={() => setImportQueueModalOpen(false)} title="ИМПОРТ → РЕГЕН: ОЧЕРЕДЬ И ИСТОРИЯ">
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

              <div className="max-h-[520px] overflow-auto pr-1 grid gap-2">
                {(importQueueView === "history" ? pipelineHistory : pipelineActive).map((it) => {
                  const st = String(it.status || "").toLowerCase();
                  const stage = String(it.stage || "").toLowerCase();
                  const terminal = st === "finished" || st === "failed" || stage === "canceled" || st === "canceled";
                  const label = String(it.title || "");
                  const badge = badgeFor(it);
                  return (
                    <div key={`${it.kind}:${it.job_id}`} className="rounded-xl border border-zinc-200 bg-white p-3">
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
                          <Button
                            variant="outline"
                            className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                            onClick={() => {
                              setSelectedJobId(String(it.job_id));
                              setJobPanelOpen(true);
                              setImportQueueModalOpen(false);
                            }}
                          >
                            ОТКРЫТЬ
                          </Button>
                          {it.kind === "import" && st === "finished" && String(it?.module_id || "").trim() ? (
                            <Button
                              variant="primary"
                              className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                              onClick={() => openModuleFromImport(it as any)}
                            >
                              МОДУЛЬ
                            </Button>
                          ) : null}
                          {it.kind === "import" && st === "failed" ? (
                            <Button
                              variant="outline"
                              className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                              onClick={() => void retryImportJob(String(it.job_id))}
                            >
                              ПОВТОРИТЬ
                            </Button>
                          ) : null}
                          {it.kind === "regen" ? (
                            <Button
                              variant="destructive"
                              className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                              disabled={terminal}
                              onClick={() => void cancelImportJob(String(it.job_id))}
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
                    </div>
                  );
                })}
              </div>
            </div>
          </Modal>
        </div>

        <div className="lg:col-span-5">
          {jobPanelOpen ? (
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
                    {String(jobKind || "").toLowerCase() === "regen" ? (
                      <button
                        type="button"
                        className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[9px] font-black uppercase tracking-widest text-rose-800 hover:bg-rose-100"
                        disabled={
                          !selectedJobId ||
                          cancelBusy ||
                          ["finished", "failed"].includes(String(jobStatus || "")) ||
                          String(jobStage || "") === "canceled"
                        }
                        onClick={() => void cancelCurrentJob()}
                      >
                        {cancelBusy ? "..." : "ОТМЕНА"}
                      </button>
                    ) : null}
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
                    {jobError ? (
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
                              {String((jobResult as any)?.regen_job_id || "").trim() ? (
                                <Button
                                  variant="outline"
                                  className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                                  onClick={() => {
                                    const rid = String((jobResult as any)?.regen_job_id || "").trim();
                                    if (!rid) return;
                                    setSelectedJobId(rid);
                                    setJobPanelOpen(true);
                                  }}
                                >
                                  ОТКРЫТЬ РЕГЕН
                                </Button>
                              ) : null}
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
          ) : (
            <div className="rounded-[22px] border border-zinc-200 bg-white/70 backdrop-blur-md p-6 shadow-2xl shadow-zinc-950/10">
              <div className="text-[11px] font-bold text-zinc-500">Открой задачу из очереди</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
