"use client";

import * as React from "react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { ImportJobItem, RegenJobItem, AdminModuleItem, StorageObjectItem } from "../types";

interface ImportTabProps {
  importFiles: File[];
  importInputRef: React.RefObject<HTMLInputElement | null>;
  setImportFiles: (files: File[]) => void;
  importStageLabel: string;
  uploadHistory?: {
    id: string;
    filename: string;
    created_at: string;
    status: "finished" | "failed" | "canceled";
    detail?: string;
  }[];
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
  importQueueWorkers: number;
  loadImportQueue: (limit?: number, includeTerminal?: boolean) => Promise<void>;
  storageUploads: StorageObjectItem[];
  storageUploadsLoading: boolean;
  storageUploadsPrefix: string;
  storageUploadsDebug?: any;
  loadStorageUploads: (prefixOverride?: string) => Promise<void>;
  enqueueImportFromS3: (objectKey: string) => void;
  adminModules: AdminModuleItem[];
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
  regenQueueWorkers: number;
  setRegenQueueModalOpen: (open: boolean) => void;
  regenQueueModalOpen: boolean;
  regenHistory: any[];
  clearAdminJobHistory: () => Promise<void>;
  jobPanelOpen: boolean;
  selectedJobId: string;
  jobStatus: string;
  jobStage: string;
  jobStageAt: string;
  jobStageStartedAt: string;
  jobStageDurations: Record<string, number> | null;
  jobStartedAt: string;
  importJobStageLabel: string;
  copy: (text: string) => void;
  cancelCurrentJob: () => void;
  cancelBusy: boolean;
  jobKind: string;
  jobModuleTitle: string;
  jobModuleId?: string;
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
  cancelActiveUpload: () => void | Promise<void>;
}

export default function ImportTab(props: ImportTabProps) {
  const {
    importFiles,
    importInputRef,
    setImportFiles,
    importStageLabel,
    uploadHistory,
    s3UploadProgress,
    importPendingCount,
    importPendingNames,
    importEnqueueProgress,
    importBatch,
    importBusy,
    startImport,
    importQueue,
    importQueueLoading,
    importQueueWorkers,
    loadImportQueue,
    storageUploads,
    storageUploadsLoading,
    storageUploadsPrefix,
    storageUploadsDebug,
    loadStorageUploads,
    enqueueImportFromS3,
    adminModules,
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
    regenQueueWorkers,
    setRegenQueueModalOpen,
    regenQueueModalOpen,
    regenHistory,
    clearAdminJobHistory,
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
    cancelActiveUpload,
  } = props;

  const moduleTitleById = useMemo(() => {
    const out: Record<string, string> = {};
    try {
      for (const m of adminModules || []) {
        const id = String((m as any)?.id || "").trim();
        if (!id) continue;
        const t = String((m as any)?.title || "").trim();
        if (!t) continue;
        out[id] = t;
      }
    } catch {
      // ignore
    }
    return out;
  }, [adminModules]);

  const regenTitleFor = (it: any): string => {
    const subTitle = String(it?.submodule_title || "").trim();
    if (subTitle) return subTitle;

    const modTitle = String(it?.module_title || "").trim();
    if (modTitle) return modTitle;

    const mid = String(it?.module_id || it?.meta?.module_id || "").trim();
    const fallback = mid ? String(moduleTitleById[mid] || "").trim() : "";
    if (fallback) return fallback;

    const title = String(it?.title || "").trim();
    // Never show raw UUID/job-id-like values as a user-facing title.
    const looksLikeUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(title);
    if (title && !looksLikeUuid) return title;
    if (mid) return mid;
    return "—";
  };

  const [storagePrefixDraft, setStoragePrefixDraft] = useState(storageUploadsPrefix || "uploads/");

  React.useEffect(() => {
    setStoragePrefixDraft(storageUploadsPrefix || "uploads/");
  }, [storageUploadsPrefix]);

  React.useEffect(() => {
    void loadStorageUploads(storageUploadsPrefix || "uploads/");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  type PipelineKind = "import" | "regen" | "upload";
  type PipelineItem = {
    kind: PipelineKind;
    job_id: string;
    title: string;
    created_at?: string;
    status?: string;
    stage?: string;
    stage_at?: string;
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

    const stClient = String(clientImportStage || "").trim().toLowerCase();
    const uploadRunning = stClient === "upload_s3" || stClient === "upload";
    if (uploadRunning) {
      out.push({
        kind: "upload",
        job_id: `upload:active:${String(clientImportFileName || "").trim() || "zip"}`,
        title: String(clientImportFileName || "").trim() || "ZIP",
        created_at: undefined,
        status: "started",
        stage: stClient,
        detail:
          stClient === "upload_s3" && s3Label
            ? `${s3Label.percent}% · ${s3Label.loadedHuman} / ${s3Label.totalHuman}`
            : "UPLOAD",
      });
    }

    for (const it of importQueue || []) {
      const jid = String((it as any)?.job_id || (it as any)?.id || "").trim();
      if (!jid) continue;
      const st = String((it as any)?.status || "").trim().toLowerCase();
      // Only include pending jobs in the "Queue" list. 
      // Active jobs ('started') will be shown in the Current Job panel.
      if (st !== "queued" && st !== "deferred" && st !== "scheduled") continue;
      out.push({
        kind: "import",
        job_id: jid,
        title: String(it.module_title || it.title || it.source_filename || "ZIP"),
        created_at: it.created_at,
        status: it.status,
        stage: it.stage,
        stage_at: (it as any)?.stage_at,
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
      const jid = String((it as any)?.job_id || (it as any)?.id || "").trim();
      if (!jid) continue;
      const st = String((it as any)?.status || "").trim().toLowerCase();
      // Only include pending jobs in the "Queue" list.
      if (st !== "queued" && st !== "deferred" && st !== "scheduled") continue;
      const subTitle = String((it as any)?.submodule_title || "").trim();
      out.push({
        kind: "regen",
        job_id: jid,
        title: String(subTitle ? `УРОК: ${subTitle}` : (it as any)?.module_title || (it as any)?.module_id || "МОДУЛЬ"),
        created_at: it.created_at,
        status: it.status,
        stage: it.stage,
        stage_at: (it as any)?.stage_at,
        detail: it.detail,
        error: it.error,
        error_code: it.error_code,
        error_hint: it.error_hint,
        error_message: it.error_message,
        module_id: it.module_id,
        module_title: it.module_title,
        submodule_id: (it as any).submodule_id,
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
  }, [clientImportStage, clientImportFileName, s3Label, importQueue, regenQueue]);

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

  const storageRows = useMemo(() => {
    const hideKeys = new Set<string>();
    try {
      for (const it of importQueue || []) {
        const k = String((it as any)?.object_key || "").trim();
        if (k) hideKeys.add(k);
      }
    } catch {
      // ignore
    }

    const occupiedKeys = new Set<string>();
    try {
      for (const m of adminModules || []) {
        const k = String((m as any)?.import_object_key || "").trim();
        if (k) occupiedKeys.add(k);
      }
    } catch {
      // ignore
    }

    const normalizeTitle = (v: string): string => {
      let s = String(v || "").trim().toLowerCase();
      if (!s) return "";
      s = s.replace(/\.zip$/i, "");
      s = s.replace(/\s+/g, " ");
      // Strip typical hash-like suffixes in filenames:
      // - "module-<hash>", "module_<hash>", "module (<hash>)", "module__<hash>"
      s = s.replace(/\s*\(?[0-9a-f]{6,64}\)?\s*$/i, "");
      s = s.replace(/[-_]+[0-9a-f]{6,64}$/i, "");
      s = s.replace(/\s*__\s*[0-9a-f]{6,64}$/i, "");
      s = s.replace(/[\[\]().,]+/g, " ");
      s = s.replace(/[-_]+/g, " ");
      s = s.replace(/\s+/g, " ").trim();
      return s;
    };

    const existingTitles = new Set<string>();
    try {
      for (const m of adminModules || []) {
        const t = normalizeTitle(String((m as any)?.title || ""));
        if (t) existingTitles.add(t);
      }
    } catch {
      // ignore
    }

    const items = storageUploads || [];

    const naturalParts = (s: string): (string | number)[] => {
      const out: (string | number)[] = [];
      const raw = String(s || "");
      const re = /(\d+)|(\D+)/g;
      let m: RegExpExecArray | null;
      while ((m = re.exec(raw)) !== null) {
        if (m[1] != null) out.push(Number(m[1]));
        else out.push(String(m[2] || "").toLowerCase());
      }
      return out;
    };

    const naturalCompare = (a: string, b: string): number => {
      const ax = naturalParts(a);
      const bx = naturalParts(b);
      const n = Math.max(ax.length, bx.length);
      for (let i = 0; i < n; i++) {
        const av = ax[i];
        const bv = bx[i];
        if (av === undefined) return -1;
        if (bv === undefined) return 1;
        if (typeof av === "number" && typeof bv === "number") {
          if (av !== bv) return av - bv;
          continue;
        }
        const as = String(av);
        const bs = String(bv);
        if (as !== bs) return as < bs ? -1 : 1;
      }
      return 0;
    };

    const displayNameForKey = (key: string): string => {
      const raw = String(key || "").trim();
      if (!raw) return "";
      const parts = raw.split("/").filter(Boolean);
      const zipPart = parts.find((p) => String(p || "").toLowerCase().endsWith(".zip"));
      return zipPart || parts[parts.length - 1] || raw;
    };

    return items
      .map((it: any) => {
        const key = String(it.key || "").trim();
        if (!key) return null;
        if (hideKeys.has(key)) return null;
        if (occupiedKeys.has(key)) return null;
        if (key.endsWith("/")) return null;

        const lower = key.toLowerCase();
        if (!lower.endsWith(".zip")) return null;

        const name = displayNameForKey(key) || key;
        const inferredTitle = normalizeTitle(name);
        if (inferredTitle && existingTitles.has(inferredTitle)) return null;
        const size = typeof it.size === "number" ? Number(it.size) : Number(it.size || 0);
        const lmRaw = (it as any)?.last_modified;
        const lm = lmRaw ? String(lmRaw) : "";
        return { key, name, size, lm };
      })
      .filter((x): x is { key: string; name: string; size: number; lm: string } => !!(x as any)?.key)
      .sort((a, b) => naturalCompare(a.name, b.name));
  }, [storageUploads, importQueue, adminModules]);

  const pipelineHistory = useMemo(() => {
    const out: PipelineItem[] = [];

    for (const it of uploadHistory || []) {
      const hid = String((it as any)?.id || "").trim();
      const fn = String((it as any)?.filename || "").trim() || "ZIP";
      out.push({
        kind: "upload",
        job_id: hid || `upload:hist:${fn}:${Math.random().toString(16).slice(2)}`,
        title: fn,
        created_at: String((it as any)?.created_at || "") || undefined,
        status: String((it as any)?.status || "finished") || undefined,
        stage: String((it as any)?.detail || "") || undefined,
        detail: String((it as any)?.detail || "") || undefined,
      });
    }

    for (const it of importQueueHistory || []) {
      out.push({
        kind: "import",
        job_id: String(it.job_id),
        title: String(it.module_title || it.title || it.source_filename || "ZIP"),
        created_at: it.created_at,
        status: it.status,
        stage: it.stage,
        stage_at: (it as any)?.stage_at,
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

      const st0 = String((it as any)?.status || "").trim().toLowerCase();
      const stage0 = String((it as any)?.stage || "").trim().toLowerCase();
      const terminal0 = st0 === "finished" || st0 === "failed" || st0 === "canceled" || st0 === "missing" || stage0 === "canceled" || stage0 === "done" || stage0 === "missing";
      if (!terminal0) continue;

      const normalizedStage = (st0 === "queued" || st0 === "deferred" || st0 === "scheduled") ? "queued" : String((it as any)?.stage || "") || undefined;
      out.push({
        kind: "regen",
        job_id: jid,
        title: String(subTitle ? `УРОК: ${subTitle}` : (it as any)?.module_title || (it as any)?.module_id || "МОДУЛЬ"),
        created_at: String((it as any)?.created_at || "") || undefined,
        status: String((it as any)?.status || "") || undefined,
        stage: normalizedStage,
        stage_at: String((it as any)?.stage_at || "") || undefined,
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
  }, [uploadHistory, importQueueHistory, regenHistory]);

  const badgeFor = (it: PipelineItem) => {
    const st = String(it.status || "").toLowerCase();
    const stage = String(it.stage || "").toLowerCase();
    if (st === "finished") return "ГОТОВО";
    if (st === "failed") return "ОШИБКА";
    if (stage === "canceled" || st === "canceled") return "ОТМЕНЕНО";
    if (st === "queued" || st === "deferred" || st === "scheduled") return "В ОЧЕРЕДИ";
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

  const isStartedJobLike = (it: any): boolean => {
    const st = String((it as any)?.status || "").trim().toLowerCase();
    return st === "started";
  };

  const isPendingJobLike = (it: any): boolean => {
    const st = String((it as any)?.status || "").trim().toLowerCase();
    return st === "queued" || st === "deferred" || st === "scheduled";
  };

  const isTerminalJobLike = (it: any): boolean => {
    const st = String((it as any)?.status || "").trim().toLowerCase();
    const stage = String((it as any)?.stage || "").trim().toLowerCase();
    return st === "finished" || st === "failed" || st === "canceled" || stage === "canceled" || stage === "done";
  };

  const timeOfJobLike = (x: any) => {
    const a = String(x?.stage_at || "").trim();
    const b = String(x?.created_at || "").trim();
    const t1 = a ? Date.parse(a) : 0;
    const t2 = b ? Date.parse(b) : 0;
    const t = t1 || t2 || 0;
    return Number.isFinite(t) ? t : 0;
  };

  const currentJobFor = (kind: "import" | "regen") => {
    const xs = (kind === "import" ? (importQueue as any[]) : (regenQueue as any[])) || [];
    // Current panel must be stable: pick the most recently updated started job.
    const started = xs.filter((it) => isStartedJobLike(it));
    if (started.length) {
      started.sort((a, b) => timeOfJobLike(b) - timeOfJobLike(a));
      return started[0] as any;
    }
    // Import UX: if there is no started job but the queue is not empty, show the next queued job.
    // Regen UX: Current must only show truly running jobs; queued must stay in the queue list.
    if (kind === "import") {
      try {
        const pending = xs.filter((it) => isPendingJobLike(it));
        if (pending.length) {
          pending.sort((a, b) => timeOfJobLike(a) - timeOfJobLike(b));
          return pending[0] as any;
        }
      } catch {
        // ignore
      }
    }
    // Product UX: keep the last finished/failed/canceled job visible in the "current" panel
    // until a new job appears.
    try {
      const hist = (pipelineHistory || []).filter((it: PipelineItem) => it.kind === kind);
      if (hist.length) return hist[0] as any;
    } catch {
      // ignore
    }
    return null;
  };

  const stickyRegenRef = React.useRef<{ job: any; ts: number } | null>(null);
  const stickyImportRef = React.useRef<{ job: any; ts: number } | null>(null);

  const currentRegenJob = React.useMemo(() => {
    const xs = (regenQueue as any[]) || [];
    const started = xs.filter((it) => isStartedJobLike(it));
    if (started.length) {
      started.sort((a, b) => timeOfJobLike(b) - timeOfJobLike(a));
      const j = started[0] as any;
      stickyRegenRef.current = { job: j, ts: Date.now() };
      return j;
    }
    const hist = (pipelineHistory || []).filter((it: PipelineItem) => it.kind === "regen");
    const terminal = hist.filter((it: any) => isTerminalJobLike(it));
    terminal.sort((a: any, b: any) => timeOfJobLike(b) - timeOfJobLike(a));
    const lastTerminal = terminal[0];
    if (lastTerminal) {
      stickyRegenRef.current = { job: lastTerminal as any, ts: Date.now() };
      return lastTerminal as any;
    }
    const sticky = stickyRegenRef.current;
    if (sticky && Date.now() - sticky.ts < 15_000) return sticky.job;
    return null;
  }, [regenQueue, pipelineHistory]);

  const currentImportJob = React.useMemo(() => {
    const xs = (importQueue as any[]) || [];
    const started = xs.filter((it) => isStartedJobLike(it));
    if (started.length) {
      started.sort((a, b) => timeOfJobLike(b) - timeOfJobLike(a));
      const j = started[0] as any;
      stickyImportRef.current = { job: j, ts: Date.now() };
      return j;
    }
    const hist = (pipelineHistory || []).filter((it: PipelineItem) => it.kind === "import");
    const terminal = hist.filter((it: any) => isTerminalJobLike(it));
    terminal.sort((a: any, b: any) => timeOfJobLike(b) - timeOfJobLike(a));
    const lastTerminal = terminal[0];
    if (lastTerminal) {
      stickyImportRef.current = { job: lastTerminal as any, ts: Date.now() };
      return lastTerminal as any;
    }
    const sticky = stickyImportRef.current;
    if (sticky && Date.now() - sticky.ts < 15_000) return sticky.job;
    return null;
  }, [importQueue, pipelineHistory]);

  const currentRegenJobId = String(currentRegenJob?.job_id || currentRegenJob?.id || "").trim();
  const currentImportJobId = String(currentImportJob?.job_id || currentImportJob?.id || "").trim();

  const activeRegenModuleId = (() => {
    if (!isStartedJobLike(currentRegenJob)) return "";
    return String(currentRegenJob?.module_id || currentRegenJob?.meta?.module_id || "").trim();
  })();

  const regenHasPending = useMemo(() => {
    try {
      return (regenQueue || []).some((it: any) => isPendingJobLike(it));
    } catch {
      return false;
    }
  }, [regenQueue]);

  const regenPendingCount = useMemo(() => {
    try {
      return (regenQueue || []).filter((it: any) => isPendingJobLike(it)).length;
    } catch {
      return 0;
    }
  }, [regenQueue]);

  const importPendingQueueCount = useMemo(() => {
    try {
      return (importQueue || []).filter((it: any) => isPendingJobLike(it)).length;
    } catch {
      return 0;
    }
  }, [importQueue]);

  const importHasPending = useMemo(() => {
    try {
      return (importQueue || []).some((it: any) => isPendingJobLike(it));
    } catch {
      return false;
    }
  }, [importQueue]);

  const [uploadOverlayMinimized, setUploadOverlayMinimized] = useState(false);

  const uploadActive = (() => {
    if (!importBusy) return false;
    const st = String(clientImportStage || "").trim().toLowerCase();
    if (!st) return false;
    return st !== "processing" && st !== "done" && st !== "failed" && st !== "canceled";
  })();

  React.useEffect(() => {
    if (!uploadActive) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
      return "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [uploadActive]);

  const importActive = (() => {
    if (!importBusy) return false;
    const st = String(clientImportStage || "").trim().toLowerCase();
    if (!st) return false;
    return st !== "done" && st !== "failed" && st !== "canceled";
  })();

  return (
    <div className="mt-8 space-y-6">
      {uploadActive ? (
        <div className="rounded-2xl border border-zinc-200 bg-white p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ЗАГРУЗКА В STORAGE</div>
              {String(clientImportFileName || "").trim() ? (
                <div className="mt-1 text-[11px] font-bold text-zinc-800 break-words">{String(clientImportFileName || "").trim()}</div>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="h-9 rounded-xl border border-rose-200 bg-rose-50 px-3 text-[9px] font-black uppercase tracking-widest text-rose-800 hover:bg-rose-100 disabled:opacity-60"
                onClick={() => void cancelActiveUpload()}
              >
                ОТМЕНА
              </button>
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
          </div>

          <div className="mt-2 text-[10px] font-bold text-zinc-700">Не обновляй страницу и не закрывай вкладку — иначе загрузка прервётся.</div>

          {String(clientImportStage || "").trim().toLowerCase() === "upload_s3" && s3Label ? (
            <div className="mt-3">
              <div className="mt-2 h-2 w-full rounded-full bg-white border border-zinc-200 overflow-hidden">
                <div className="h-full bg-[#fe9900] transition-all" style={{ width: `${s3Label.percent}%` }} />
              </div>

              {importHasPending && (!isStartedJobLike(currentImportJob)) && Number(importQueueWorkers || 0) <= 0 ? (
                <div className="mt-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[10px] font-bold text-rose-800">
                  Очередь импорта не исполняется: нет воркера для очереди.
                </div>
              ) : null}
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

      <div className="rounded-[22px] border border-zinc-200 bg-white/70 backdrop-blur-md p-3 shadow-2xl shadow-zinc-950/10">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-[220px]">
            <div className="text-[9px] font-black uppercase tracking-[0.28em] text-zinc-500">ФАЙЛЫ В STORAGE (S3)</div>
            <div className="mt-2 text-[10px] font-bold text-zinc-600">
              Префикс: <span className="font-mono">{String(storageUploadsPrefix || "uploads/admin/")}</span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <input
              value={storagePrefixDraft}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setStoragePrefixDraft(String(e.target.value || ""))}
              className="h-9 w-[260px] rounded-xl border border-zinc-200 bg-white px-3 text-[11px] font-bold text-zinc-800"
              placeholder="uploads/admin/"
            />
            <button
              type="button"
              className="h-9 rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50 disabled:opacity-60"
              disabled={storageUploadsLoading}
              onClick={() => void loadStorageUploads(storagePrefixDraft)}
            >
              ОБНОВИТЬ
            </button>
          </div>
        </div>

        <div className="mt-3">
          {storageUploadsLoading ? (
            <div className="text-[11px] font-bold text-zinc-600">ЗАГРУЖАЮ СПИСОК…</div>
          ) : !storageRows.length ? (
            <div className="space-y-2">
              <div className="text-[11px] font-bold text-zinc-600">НЕТ ZIP В ЭТОМ ПРЕФИКСЕ</div>
              {storageUploadsDebug ? (
                <div className="rounded-xl border border-zinc-200 bg-white px-3 py-2">
                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">DIAGNOSTICS</div>
                  <div className="mt-2 grid gap-1 text-[11px] font-bold text-zinc-700">
                    <div>
                      <span className="text-zinc-500">bucket:</span> <span className="font-mono">{String(storageUploadsDebug?.bucket || "")}</span>
                    </div>
                    <div>
                      <span className="text-zinc-500">endpoint:</span> <span className="font-mono">{String(storageUploadsDebug?.endpoint_url || "") || "(empty)"}</span>
                    </div>
                    <div>
                      <span className="text-zinc-500">prefix_norm:</span> <span className="font-mono">{String(storageUploadsDebug?.prefix_norm || "")}</span>
                    </div>
                    <div>
                      <span className="text-zinc-500">scan:</span>{" "}
                      <span className="font-mono">
                        {storageUploadsDebug?.scan
                          ? `${String((storageUploadsDebug.scan as any).used)} pages=${String((storageUploadsDebug.scan as any).pages)} sec=${String((storageUploadsDebug.scan as any).seconds)} found=${String((storageUploadsDebug.scan as any).found)}`
                          : "—"}
                      </span>
                    </div>
                  </div>

                  {Array.isArray(storageUploadsDebug?.sample_keys) && storageUploadsDebug.sample_keys.length ? (
                    <div className="mt-2">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">SAMPLE KEYS</div>
                      <div className="mt-1 max-h-[220px] overflow-auto rounded-lg border border-zinc-200 bg-zinc-50 p-2">
                        {(storageUploadsDebug.sample_keys as any[]).slice(0, 50).map((k, idx) => (
                          <div key={idx} className="font-mono text-[10px] text-zinc-700 break-all">
                            {String(k)}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {storageUploadsDebug?.sample_error ? (
                    <div className="mt-2 font-mono text-[10px] text-rose-700 break-all">{String(storageUploadsDebug.sample_error)}</div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="max-h-[520px] overflow-y-auto overflow-x-auto pr-1">
              <div className="flex flex-nowrap gap-2 min-w-max">
              {storageRows.slice(0, 80).map((it: any) => (
                <div
                  key={it.key}
                  className="shrink-0 w-[320px] rounded-xl border border-zinc-200 bg-white px-3 py-2"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-[11px] font-black text-zinc-950">{it.name}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[9px] font-black uppercase tracking-widest text-zinc-600">
                        <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1">{humanBytes(it.size)}</div>
                        {it.lm ? (
                          <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1">{String(it.lm).replace("T", " ").slice(0, 16)}</div>
                        ) : null}
                      </div>
                    </div>

                    <div className="shrink-0 flex items-center gap-2">
                      <button
                        type="button"
                        className="h-8 rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                        onClick={() => void copy(String(it.key || ""))}
                      >
                        COPY KEY
                      </button>
                      <button
                        type="button"
                        className="h-8 rounded-xl border border-[#fe9900]/30 bg-[#fe9900]/10 px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-900 hover:bg-[#fe9900]/20"
                        onClick={() => {
                          const ok = window.confirm(`Импортировать ZIP из STORAGE?\n\n${it.name}\n\n${it.key}`);
                          if (!ok) return;
                          enqueueImportFromS3(it.key);
                        }}
                      >
                        ИМПОРТ
                      </button>
                    </div>
                  </div>
                </div>
              ))}
              </div>
            </div>
          )}
        </div>

      </div>

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
                  accept=".zip,application/zip"
                  multiple
                  className="hidden"
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    const files = Array.from(e.target.files || []);
                    const zips = files.filter((f) => String(f?.name || "").toLowerCase().endsWith(".zip"));
                    setImportFiles(zips);
                  }}
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
              <button
                type="button"
                className="h-8 rounded-xl border border-zinc-200 bg-white px-3 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                onClick={() => {
                  setImportQueueView("active");
                  setImportQueueModalOpen(true);
                  void Promise.all([
                    loadImportQueue(200, true),
                    loadRegenHistory(),
                  ]);
                }}
              >
                ДЕТАЛИ
              </button>
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
            {/* Regeneration Queue */}
            <div className="mb-6">
              <div className="flex items-center justify-between gap-3 mb-3">
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">
                  РЕГЕНЕРАЦИЯ (AI)
                  <span className="ml-3 text-[9px] font-black uppercase tracking-widest text-zinc-400">
                    {regenHistoryLoading ? "..." : `ЗАДАЧ: ${regenPendingCount}`}
                  </span>
                  <span className="ml-3 text-[9px] font-black uppercase tracking-widest text-zinc-400">
                    {`WORKERS: ${Number(regenQueueWorkers || 0)}`}
                  </span>
                </div>
              </div>

              {regenHasPending && (!isStartedJobLike(currentRegenJob)) && Number(regenQueueWorkers || 0) <= 0 ? (
                <div className="mb-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[10px] font-bold text-rose-800">
                  Очередь регенерации не исполняется: нет воркера для очереди.
                </div>
              ) : null}
              
              <div className="space-y-2">
                {regenQueue.length === 0 ? (
                  <div className="text-[10px] font-bold text-zinc-400 italic px-2">Очередь регенерации пуста</div>
                ) : (
                  regenQueue
                    .filter((it: any) => {
                      if (!isPendingJobLike(it)) return false;
                      const jid = String((it as any)?.job_id || (it as any)?.id || "").trim();
                      if (currentRegenJobId && jid && jid === currentRegenJobId) return false;
                      return true;
                    })
                    .slice(0, 3)
                    .map((it) => (
                    <div
                      key={String((it as any)?.job_id || (it as any)?.id || (it as any)?.module_id || Math.random())}
                      className="flex items-center justify-between gap-3 p-2 rounded-lg bg-zinc-50 border border-zinc-100"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[10px] font-bold text-zinc-800">
                          {regenTitleFor(it) || "Модуль"}
                        </div>
                        <div className="text-[9px] text-zinc-500 uppercase font-black tracking-tighter">
                          {it.stage || it.status}
                        </div>
                      </div>

                      <div className="shrink-0 flex items-center gap-2">
                        <button
                          type="button"
                          className="h-8 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[9px] font-black uppercase tracking-widest text-rose-800 hover:bg-rose-100 disabled:opacity-60"
                          disabled={cancelBusy || !String((it as any)?.job_id || (it as any)?.id || "").trim()}
                          onClick={() => {
                            const jid = String((it as any)?.job_id || (it as any)?.id || "").trim();
                            if (!jid) return;
                            void cancelRegenJob(jid);
                          }}
                        >
                          {cancelBusy ? "..." : "ОТМЕНА"}
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Separator */}
            <div className="h-px bg-zinc-100 mb-6" />

            {/* Import Queue */}
            <div>
              <div className="flex items-center justify-between gap-3">
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">
                  ИМПОРТ (ZIP)
                  <span className="ml-3 text-[9px] font-black uppercase tracking-widest text-zinc-400">
                    {importQueueLoading ? "..." : `ЗАДАЧ: ${importPendingQueueCount}`}
                  </span>
                  <span className="ml-3 text-[9px] font-black uppercase tracking-widest text-zinc-400">
                    {`WORKERS: ${Number(importQueueWorkers || 0)}`}
                  </span>
                </div>

                {typeof importPendingCount === "number" && importPendingCount > 0 ? (
                  <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                    ОЧЕРЕДЬ ИМПОРТА: {importPendingCount}
                  </div>
                ) : null}
                <div className="flex items-center gap-2">
                </div>
              </div>

              <div className="mt-3 space-y-2">
                {importQueue.length === 0 ? (
                  <div className="text-[10px] font-bold text-zinc-400 italic px-2">Очередь импорта пуста</div>
                ) : (
                  importQueue
                    .filter((it: any) => isPendingJobLike(it))
                    .filter((it: any) => {
                      const jid = String((it as any)?.job_id || (it as any)?.id || "").trim();
                      if (currentImportJobId && jid && jid === currentImportJobId) return false;
                      return true;
                    })
                    .slice(0, 3)
                    .map((it) => (
                    <div
                      key={String((it as any)?.job_id || (it as any)?.id || (it as any)?.module_id || (it as any)?.object_key || Math.random())}
                      className="flex items-center justify-between gap-3 p-2 rounded-lg bg-zinc-50 border border-zinc-100"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[10px] font-bold text-zinc-800">
                          {it.module_title || it.title || it.source_filename || "ZIP"}
                        </div>
                        <div className="text-[9px] text-zinc-500 uppercase font-black tracking-tighter">
                          {it.stage || it.status}
                        </div>
                      </div>

                      <div className="shrink-0 flex items-center gap-2">
                        <button
                          type="button"
                          className="h-8 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[9px] font-black uppercase tracking-widest text-rose-800 hover:bg-rose-100 disabled:opacity-60"
                          disabled={
                            cancelBusy ||
                            !String((it as any)?.job_id || (it as any)?.id || "").trim() ||
                            !canCancelImport(it)
                          }
                          onClick={() => {
                            const jid = String((it as any)?.job_id || (it as any)?.id || "").trim();
                            if (!jid) return;
                            void cancelImportJob(jid);
                          }}
                        >
                          {cancelBusy ? "..." : "ОТМЕНА"}
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

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
          </div>

          <Modal
            open={importQueueModalOpen}
            onClose={() => setImportQueueModalOpen(false)}
            title="История"
            className="max-w-[min(96vw,1200px)]"
          >
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600">
                  {importQueueView === "history" ? "ИСТОРИЯ" : "ОЧЕРЕДЬ"}
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
                  {importQueueView === "history" ? (
                    <Button
                      variant="outline"
                      className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                      onClick={() => {
                        const ok = window.confirm(
                          "Очистить историю задач?\n\nБудут удалены записи истории ИМПОРТА и РЕГЕНА из админки."
                        );
                        if (!ok) return;
                        void clearAdminJobHistory();
                      }}
                    >
                      ОЧИСТИТЬ
                    </Button>
                  ) : null}
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
                        if (it.kind === "upload") return;
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
                              {it.kind === "import" ? "IMPORT" : it.kind === "regen" ? "REGEN" : "UPLOAD"}
                            </div>
                            <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                              {badge}
                            </div>
                            {String(it.created_at || "").trim() ? (
                              <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                {String(it.created_at || "").replace("T", " ").slice(0, 16)}
                              </div>
                            ) : null}
                            {it.kind !== "upload" && String(it.stage || "").trim() ? (
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
                              onClick={(e: React.MouseEvent<HTMLButtonElement>) => {
                                e.preventDefault();
                                e.stopPropagation();
                                openModuleFromImport(it as any);
                              }}
                            >
                              МОДУЛЬ
                            </Button>
                          ) : null}
                          {it.kind === "import" ? (
                            <Button
                              variant="destructive"
                              className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                              disabled={terminal || cancelBusy || !canCancelImport(it)}
                              onClick={(e: React.MouseEvent<HTMLButtonElement>) => {
                                e.preventDefault();
                                e.stopPropagation();
                                void cancelImportJob(String(it.job_id));
                              }}
                            >
                              ОТМЕНА
                            </Button>
                          ) : null}
                          {it.kind === "regen" ? (
                            <Button
                              variant="destructive"
                              className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                              disabled={terminal}
                              onClick={(e: React.MouseEvent<HTMLButtonElement>) => {
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
            <div className="grid gap-3">
              {(() => {
                const it = currentRegenJob as any;
                const jid = String(it?.job_id || it?.id || "").trim();
                if (!jid) {
                  return (
                    <div className="rounded-2xl border border-zinc-200 bg-white p-3">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ТЕКУЩИЙ REGEN</div>
                      <div className="mt-2 text-[11px] font-bold text-zinc-500">НЕТ АКТИВНОГО РЕГЕНА</div>
                    </div>
                  );
                }
                const badge = (() => {
                  const st = String(it?.status || "").trim().toLowerCase();
                  if (st === "started") return "В РАБОТЕ";
                  if (st === "queued" || st === "deferred" || st === "scheduled") return "В ОЧЕРЕДИ";
                  if (st === "finished") return "ГОТОВО";
                  if (st === "failed") return "ОШИБКА";
                  if (st === "canceled") return "ОТМЕНЕНО";
                  return st ? st.toUpperCase() : "—";
                })();
                const label = regenTitleFor(it);
                const detail = String(it?.detail || "").trim() || "—";
                const err = String(it?.error || "").trim();
                return (
                  <div className="rounded-2xl border border-zinc-200 bg-white p-3">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ТЕКУЩИЙ REGEN</div>
                        <div className="mt-1 truncate text-[11px] font-black text-zinc-950">{label}</div>
                        <div className="mt-1 text-[10px] font-bold text-zinc-600 break-words">ТИП: REGEN</div>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">{badge}</div>
                        </div>
                      </div>

                      <div className="shrink-0 flex items-center gap-2">
                        <button
                          type="button"
                          className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                          disabled={!jid}
                          onClick={() => void copy(jid)}
                        >
                          КОПИРОВАТЬ
                        </button>
                        <button
                          type="button"
                          className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                          disabled={!jid}
                          onClick={() => {
                            setSelectedJobId(jid);
                            setJobPanelOpen(true);
                          }}
                        >
                          ОТКРЫТЬ
                        </button>
                        <button
                          type="button"
                          className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[9px] font-black uppercase tracking-widest text-rose-800 hover:bg-rose-100 disabled:opacity-60"
                          disabled={!jid || cancelBusy}
                          onClick={() => void cancelRegenJob(jid)}
                        >
                          {cancelBusy ? "..." : "ОТМЕНА"}
                        </button>
                      </div>
                    </div>

                    <div className="mt-3 grid gap-3 sm:grid-cols-2">
                      <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ДЕТАЛЬ</div>
                        <div className="mt-2 text-[11px] font-bold text-zinc-950 break-words max-h-[84px] overflow-auto pr-1">{detail}</div>
                      </div>
                      <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ОШИБКА</div>
                        {err ? (
                          <div className="mt-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-[10px] font-bold text-rose-800 break-words max-h-[84px] overflow-auto pr-1">
                            {err}
                          </div>
                        ) : (
                          <div className="mt-2 text-[11px] font-bold text-zinc-500">—</div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })()}

              {(() => {
                const it = currentJobFor("import") as any;
                const jid = String(it?.job_id || it?.id || "").trim();
                const st = String(it?.status || "").trim().toLowerCase();
                const stage = String(it?.stage || "").trim().toLowerCase();
                const terminal = st === "finished" || st === "failed" || st === "canceled" || stage === "canceled";
                if (!jid) {
                  return (
                    <div className="rounded-2xl border border-zinc-200 bg-white p-3">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ТЕКУЩИЙ IMPORT</div>
                      <div className="mt-2 text-[11px] font-bold text-zinc-500">НЕТ АКТИВНОГО ИМПОРТА</div>
                    </div>
                  );
                }
                const badge = (() => {
                  if (terminal) return st === "finished" ? "ГОТОВО" : st === "failed" ? "ОШИБКА" : "ОТМЕНЕНО";
                  if (st === "queued" || st === "deferred" || st === "scheduled") return "В ОЧЕРЕДИ";
                  return "В РАБОТЕ";
                })();
                const label = String(it?.module_title || it?.title || "—") || "—";
                const detail = String(it?.detail || "").trim() || "—";
                const err = String(it?.error || "").trim();
                return (
                  <div className="rounded-2xl border border-zinc-200 bg-white p-3">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ТЕКУЩИЙ IMPORT</div>
                        <div className="mt-1 truncate text-[11px] font-black text-zinc-950">{label}</div>
                        <div className="mt-1 text-[10px] font-bold text-zinc-600 break-words">ТИП: IMPORT</div>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">{badge}</div>
                        </div>
                      </div>

                      <div className="shrink-0 flex items-center gap-2">
                        <button
                          type="button"
                          className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                          disabled={!jid}
                          onClick={() => void copy(jid)}
                        >
                          КОПИРОВАТЬ
                        </button>
                        <button
                          type="button"
                          className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                          disabled={!jid}
                          onClick={() => {
                            setSelectedJobId(jid);
                            setJobPanelOpen(true);
                          }}
                        >
                          ОТКРЫТЬ
                        </button>
                        <button
                          type="button"
                          className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[9px] font-black uppercase tracking-widest text-rose-800 hover:bg-rose-100 disabled:opacity-60"
                          disabled={!jid || cancelBusy || terminal || !canCancelImport(it)}
                          onClick={() => void cancelImportJob(jid)}
                        >
                          {cancelBusy ? "..." : "ОТМЕНА"}
                        </button>
                      </div>
                    </div>

                    <div className="mt-3 grid gap-3 sm:grid-cols-2">
                      <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ДЕТАЛЬ</div>
                        <div className="mt-2 text-[11px] font-bold text-zinc-950 break-words max-h-[84px] overflow-auto pr-1">{detail}</div>
                      </div>
                      <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ОШИБКА</div>
                        {err ? (
                          <div className="mt-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-[10px] font-bold text-rose-800 break-words max-h-[84px] overflow-auto pr-1">
                            {err}
                          </div>
                        ) : (
                          <div className="mt-2 text-[11px] font-bold text-zinc-500">—</div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })()}
            </div>

            {importActive ? (
              <div className="mt-3 rounded-2xl border border-zinc-200 bg-white p-3">
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ЗАГРУЗКА НА ХРАНИЛИЩЕ</div>
                {String(clientImportFileName || "").trim() ? (
                  <div className="mt-1 text-[11px] font-bold text-zinc-950 break-words">{String(clientImportFileName || "").trim()}</div>
                ) : null}

                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                    {String(importStageLabel || "—")}
                  </div>
                  {importBatch ? (
                    <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                      {`${Number(importBatch.done || 0)}/${Number(importBatch.total || 0)}`}
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
