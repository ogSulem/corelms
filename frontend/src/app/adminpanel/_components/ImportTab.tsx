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
    setRegenQueueModalOpen,
    regenQueueModalOpen,
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
                ОЧЕРЕДЬ ИМПОРТА
                <span className="ml-3 text-[9px] font-black uppercase tracking-widest text-zinc-400">
                  {importQueueLoading ? "..." : `ЗАДАЧ: ${importQueue.length}`}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                  onClick={() => void loadImportQueue(20, false)}
                  disabled={importQueueLoading}
                >
                  {importQueueLoading ? "..." : "ОБНОВИТЬ"}
                </button>
                <button
                  type="button"
                  className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                  onClick={() => {
                    setImportQueueView("active");
                    setImportQueueModalOpen(true);
                    void loadImportQueue(50, true);
                  }}
                >
                  ВСЯ ОЧЕРЕДЬ
                </button>
              </div>
            </div>

            <div className="mt-3 grid gap-2">
              {(importQueue || []).slice(0, 5).map((it) => {
                const st = String(it.status || "").toLowerCase();
                const stage = String(it.stage || "").toLowerCase();
                const terminal = st === "finished" || st === "failed" || stage === "canceled" || st === "canceled";
                const displayName = String(it.module_title || it.title || it.source_filename || "ZIP");
                const badge = (() => {
                  if (st === "failed") return "ОШИБКА";
                  if (stage === "canceled" || st === "canceled") return "ОТМЕНЕНО";
                  if (st === "queued" || st === "deferred") return "В ОЧЕРЕДИ";
                  if (st === "started") return "В РАБОТЕ";
                  return "В РАБОТЕ";
                })();
                return (
                  <div key={it.job_id} className="flex items-center justify-between gap-3 rounded-xl border border-zinc-200 bg-white px-3 py-2">
                    <div className="min-w-0">
                      <div className="truncate text-[10px] font-black uppercase tracking-widest text-zinc-900">
                        {displayName}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                          {badge}
                        </div>
                        <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                          {stage ? stage.toUpperCase() : "—"}
                        </div>
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
                      <button
                        type="button"
                        className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[9px] font-black uppercase tracking-widest text-rose-800 hover:bg-rose-100"
                        disabled={terminal}
                        onClick={() => void cancelImportJob(String(it.job_id))}
                      >
                        ОТМЕНА
                      </button>
                    </div>
                  </div>
                );
              })}
              {!importQueueLoading && !(importQueue || []).length ? (
                <div className="text-[10px] font-bold text-zinc-500">—</div>
              ) : null}
            </div>
          </div>

          <Modal open={importQueueModalOpen} onClose={() => setImportQueueModalOpen(false)} title="ОЧЕРЕДЬ ИМПОРТА">
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600">
                  {importQueueView === "history" ? "ИСТОРИЯ" : "АКТИВНЫЕ"}
                  <span className="ml-2 text-zinc-400">
                    {importQueueLoading
                      ? "..."
                      : importQueueView === "history"
                        ? importQueueHistory.length
                        : importQueue.length}
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
                    onClick={() => void loadImportQueue(50, true)}
                  >
                    ОБНОВИТЬ
                  </Button>
                </div>
              </div>

              <div className="max-h-[520px] overflow-auto pr-1 grid gap-2">
                {((importQueueView === "history" ? importQueueHistory : importQueue) || []).map((it) => {
                  const st = String(it.status || "").toLowerCase();
                  const stage = String(it.stage || "").toLowerCase();
                  const terminal = st === "finished" || st === "failed" || stage === "canceled" || st === "canceled";
                  const label = String(it.module_title || it.title || it.source_filename || "ZIP");
                  const badge = (() => {
                    if (st === "finished") return "ГОТОВО";
                    if (st === "failed") return "ОШИБКА";
                    if (stage === "canceled" || st === "canceled") return "ОТМЕНЕНО";
                    if (st === "queued" || st === "deferred") return "В ОЧЕРЕДИ";
                    if (st === "started") return "В РАБОТЕ";
                    return (st || "—").toUpperCase();
                  })();
                  return (
                    <div key={it.job_id} className="rounded-xl border border-zinc-200 bg-white p-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-[10px] font-black uppercase tracking-widest text-zinc-900">{label}</div>
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                              {badge}
                            </div>
                            {importQueueView === "history" ? (
                              <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                {String(it.job_id || "").slice(0, 10)}
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
                          {st === "finished" && String((it as any)?.module_id || "").trim() ? (
                            <Button
                              variant="primary"
                              className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                              onClick={() => openModuleFromImport(it)}
                            >
                              МОДУЛЬ
                            </Button>
                          ) : null}
                          {st === "failed" ? (
                            <Button
                              variant="outline"
                              className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                              onClick={() => void retryImportJob(String(it.job_id))}
                            >
                              ПОВТОРИТЬ
                            </Button>
                          ) : null}
                          <Button
                            variant="destructive"
                            className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                            disabled={terminal}
                            onClick={() => void cancelImportJob(String(it.job_id))}
                          >
                            ОТМЕНА
                          </Button>
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

          <div className="mt-3 rounded-2xl border border-zinc-200 bg-white p-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">
                ОЧЕРЕДЬ РЕГЕНА
                <span className="ml-3 text-[9px] font-black uppercase tracking-widest text-zinc-400">
                  {regenHistoryLoading ? "..." : `ЗАДАЧ: ${regenQueue.length}`}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                  onClick={() => void loadRegenHistory()}
                  disabled={regenHistoryLoading}
                >
                  {regenHistoryLoading ? "..." : "ОБНОВИТЬ"}
                </button>
                <button
                  type="button"
                  className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                  onClick={() => setRegenQueueModalOpen(true)}
                >
                  ВСЯ ИСТОРИЯ
                </button>
              </div>
            </div>

            <div className="mt-3 grid gap-2">
              {(regenQueue || []).slice(0, 5).map((it) => {
                const st = String(it.status || "").toLowerCase();
                const stage = String(it.stage || "").toLowerCase();
                const terminal = st === "finished" || st === "failed" || stage === "canceled" || st === "canceled";
                const name = String(it.module_title || it.module_id || "МОДУЛЬ");
                const badge = (() => {
                  if (st === "queued" || st === "deferred") return "В ОЧЕРЕДИ";
                  if (st === "started") return "В РАБОТЕ";
                  return "В РАБОТЕ";
                })();
                return (
                  <div key={it.job_id} className="flex items-center justify-between gap-3 rounded-xl border border-zinc-200 bg-white px-3 py-2">
                    <div className="min-w-0">
                      <div className="truncate text-[10px] font-black uppercase tracking-widest text-zinc-900">{name}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                          {badge}
                        </div>
                        <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                          {stage ? stage.toUpperCase() : "—"}
                        </div>
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
                      <button
                        type="button"
                        className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[9px] font-black uppercase tracking-widest text-rose-800 hover:bg-rose-100"
                        disabled={terminal}
                        onClick={() => void cancelImportJob(String(it.job_id))}
                      >
                        ОТМЕНА
                      </button>
                    </div>
                  </div>
                );
              })}

              {!regenHistoryLoading && !(regenQueue || []).length ? (
                <div className="text-[10px] font-bold text-zinc-500">—</div>
              ) : null}
            </div>
          </div>

          <Modal open={regenQueueModalOpen} onClose={() => setRegenQueueModalOpen(false)} title="РЕГЕНЕРАЦИЯ: ИСТОРИЯ">
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600">
                  ИСТОРИЯ
                  <span className="ml-2 text-zinc-400">{regenHistoryLoading ? "..." : (regenHistory || []).length}</span>
                </div>
                <Button
                  variant="outline"
                  className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  onClick={() => void loadRegenHistory()}
                >
                  ОБНОВИТЬ
                </Button>
              </div>
              <div className="max-h-[520px] overflow-auto pr-1 grid gap-2">
                {(regenHistory || []).map((it: any) => {
                  const jid = String(it?.job_id || it?.id || "").trim();
                  const st = String(it?.status || "").toLowerCase();
                  const stage = String(it?.stage || "").toLowerCase();
                  const name = String(it?.module_title || it?.module_id || "МОДУЛЬ");
                  const badge = (() => {
                    if (st === "finished") return "ГОТОВО";
                    if (st === "failed") return "ОШИБКА";
                    if (stage === "canceled" || st === "canceled") return "ОТМЕНЕНО";
                    if (st === "queued" || st === "deferred") return "В ОЧЕРЕДИ";
                    if (st === "started") return "В РАБОТЕ";
                    return (st || "—").toUpperCase();
                  })();
                  const key = `${jid}:${String(it?.module_id || "").trim()}:${String(it?.created_at || "").trim()}`;
                  return (
                    <div key={key} className="rounded-xl border border-zinc-200 bg-white p-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-[10px] font-black uppercase tracking-widest text-zinc-900">{name}</div>
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                              {badge}
                            </div>
                            <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                              {String(jid || "").slice(0, 10)}
                            </div>
                          </div>
                        </div>
                        <div className="shrink-0 flex items-center gap-2">
                          <Button
                            variant="outline"
                            className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                            disabled={!jid}
                            onClick={() => {
                              if (!jid) return;
                              setSelectedJobId(String(jid));
                              setJobPanelOpen(true);
                              setRegenQueueModalOpen(false);
                            }}
                          >
                            ОТКРЫТЬ
                          </Button>
                        </div>
                      </div>
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
                  <div className="mt-3 overflow-hidden rounded-xl border border-zinc-100 bg-white/50 p-3">
                    <pre className="text-[9px] font-mono text-zinc-600 whitespace-pre-wrap break-words overflow-x-hidden max-h-[420px] overflow-y-auto">
                      {JSON.stringify(jobResult, null, 2)}
                    </pre>
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
