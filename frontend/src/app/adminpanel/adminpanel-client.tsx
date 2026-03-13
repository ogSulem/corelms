"use client";

import * as React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import * as nextNavigation from "next/navigation";
import { AppShell } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/hooks/use-auth";

import {
  ImportJobItem,
  RegenJobItem,
  AdminModuleItem,
  AdminSubmoduleItem,
  AdminSubmoduleQualityItem,
  AdminQuestionItem,
  UserItem,
  UserHistoryDetailedItem,
  UserDetail,
  TabKey,
  StorageObjectItem,
  Module
} from "./types";

import { DiagnosticsTab } from "./_components/DiagnosticsTab";
import { UsersTab } from "./_components/UsersTab";
import { ModulesTab } from "./_components/ModulesTab";
import ImportTab from "./_components/ImportTab";

export default function AdminPanelClient() {
  const { user, loading: authLoading } = useAuth();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pathname = (nextNavigation as any).usePathname();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const router = (nextNavigation as any).useRouter();

  const IMPORT_STATE_KEY = "corelms:admin_import_state:v4";
  const STORAGE_UPLOADS_PREFIX_KEY = "corelms:admin_storage_uploads_prefix:v1";
  const ADMIN_UI_STATE_KEY = "corelms:admin_ui_state:v1";

  const ADMIN_CACHE_TTL_MS = 30_000;

  // --- Refs ---
  const importQueueSigRef = useRef<string>("");
  const importQueueHistorySigRef = useRef<string>("");
  const regenHistorySigRef = useRef<string>("");
  const importJobStatusByIdRef = useRef<Record<string, string>>({});
  const refreshModulesDebounceRef = useRef<number | null>(null);
  const selectedJobIdRef = useRef<string>("");
  const jobPanelOpenRef = useRef<boolean>(false);
  const jobPanelHydrateRef = useRef<{ jobId: string; lastAtMs: number }>({ jobId: "", lastAtMs: 0 });
  const longJobToastRef = useRef<{ jobId: string; stageAt: string; lastShownAtMs: number }>({ jobId: "", stageAt: "", lastShownAtMs: 0 });
  const importBatchJobIdsRef = useRef<string[]>([]);
  const importCancelRequestedRef = useRef(false);
  const importUploadAbortRef = useRef<AbortController | null>(null);
  const importUploadObjectKeyRef = useRef<string>("");
  const importUploadFilenameRef = useRef<string>("");
  const importUploadMultipartRef = useRef<{ object_key: string; upload_id: string } | null>(null);
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const importRunnerActiveRef = useRef<boolean>(false);
  const importQueuePendingRef = useRef<File[]>([]);
  const lastAdminSseRefreshMsRef = useRef<number>(0);
  const jobsSseLastOkAtRef = useRef<number>(0);
  const jobsSseLastRevRef = useRef<number>(0);
  const jobsPollInFlightRef = useRef<boolean>(false);
  const jobPanelLastStableRef = useRef<{ status: string; stage: string; stageAtUpdatedMs: number; detailUpdatedMs: number }>({ status: "", stage: "", stageAtUpdatedMs: 0, detailUpdatedMs: 0 });
  const restoredJobFromStorageRef = useRef<boolean>(false);
  const didInitFromQueryRef = useRef<boolean>(false);
  const optimisticActiveModuleRegenRef = useRef<Record<string, any>>({});
  const optimisticActiveSubmoduleRegenRef = useRef<Record<string, any>>({});

  const adminModulesLoadedAtRef = useRef<number>(0);
  const usersLoadedAtRef = useRef<number>(0);
  const systemStatusLoadedAtRef = useRef<number>(0);
  const runtimeLlmLoadedAtRef = useRef<number>(0);
  const runtimeS3LoadedAtRef = useRef<number>(0);

  const jobsDebugEnabled = useMemo(() => {
    try {
      if (process.env.NODE_ENV === "production") return false;
      return String(window.localStorage.getItem("corelms:admin_jobs_debug") || "").trim() === "1";
    } catch {
      return false;
    }
  }, []);

  const tabFromPath = (p: string): TabKey => {
    const path = String(p || "");
    if (path.startsWith("/admin/")) {
      const seg = path.split("/").filter(Boolean)[1] || "modules";
      if (seg === "modules" || seg === "import" || seg === "analytics" || seg === "users" || seg === "diagnostics") return seg;
      return "modules";
    }
    // Backwards compatibility (old route)
    if (path.startsWith("/adminpanel")) return "modules";
    return "modules";
  };

  const pathForTab = (t: TabKey): string => `/admin/${t}`;

  const goTab = (next: TabKey) => {
    const desired = pathForTab(next);
    if (pathname !== desired) router.push(desired);
    if (tab !== next) setTab(next);
  };

  const jobsLog = (label: string, data: any) => {
    if (!jobsDebugEnabled) return;
    try {
      // eslint-disable-next-line no-console
      console.log(`[admin:jobs] ${label}`, data);
    } catch {
      // ignore
    }
  };

  // --- Utilities ---
  function readAdminQuery(): { mid?: string; sid?: string; qid?: string } {
    try {
      const sp = new URLSearchParams(window.location.search || "");
      const mid = String(sp.get("mid") || "").trim();
      const sid = String(sp.get("sid") || "").trim();
      const qid = String(sp.get("qid") || "").trim();
      return {
        mid: mid || undefined,
        sid: sid || undefined,
        qid: qid || undefined,
      };
    } catch {
      return {};
    }
  }

  function loadAdminUiState(): any {
    try {
      const raw = window.sessionStorage.getItem(ADMIN_UI_STATE_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  function saveAdminUiState(patch: any) {
    try {
      const prev = loadAdminUiState() || {};
      const next = { ...prev, ...patch, _ts: Date.now() };
      window.sessionStorage.setItem(ADMIN_UI_STATE_KEY, JSON.stringify(next));
    } catch {
      // ignore
    }
  }

  // --- State ---
  const [tab, setTab] = useState<TabKey>("modules");
  const [error, setError] = useState<string | null>(null);

  // Modules
  const [adminModules, setAdminModules] = useState<AdminModuleItem[]>([]);
  const [adminModulesLoading, setAdminModulesLoading] = useState(false);
  const [selectedAdminModuleId, setSelectedAdminModuleId] = useState<string>("");
  const [selectedAdminModuleSubs, setSelectedAdminModuleSubs] = useState<AdminSubmoduleItem[]>([]);
  const [selectedAdminModuleSubsLoading, setSelectedAdminModuleSubsLoading] = useState(false);
  const [subQualityByModuleId, setSubQualityByModuleId] = useState<Record<string, AdminSubmoduleQualityItem[]>>({});
  const [subQualityLoadingByModuleId, setSubQualityLoadingByModuleId] = useState<Record<string, boolean>>({});
  const [selectedSubmoduleId, setSelectedSubmoduleId] = useState<string>("");
  const [selectedQuizId, setSelectedQuizId] = useState<string>("");
  const [questionsByQuizId, setQuestionsByQuizId] = useState<Record<string, AdminQuestionItem[]>>({});
  const [questionsLoadingQuizId, setQuestionsLoadingQuizId] = useState<string>("");
  const [questionSavingId, setQuestionSavingId] = useState<string>("");
  const [questionDraftsById, setQuestionDraftsById] = useState<Record<string, any>>({});
  const [newQuestionBusy, setNewQuestionBusy] = useState(false);

  // Users
  const [users, setUsers] = useState<UserItem[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [userQuery, setUserQuery] = useState("");
  const [selectedUserId, setSelectedUserId] = useState<string>("");
  const [userDetail, setUserDetail] = useState<UserDetail | null>(null);
  const [userDetailLoading, setUserDetailLoading] = useState(false);
  const [userHistoryDetailed, setUserHistoryDetailed] = useState<UserHistoryDetailedItem[]>([]);
  const [userHistoryLoading, setUserHistoryLoading] = useState(false);
  const [deleteUserBusy, setDeleteUserBusy] = useState(false);
  const [newUserName, setNewUserName] = useState("");
  const [newUserEmail, setNewUserEmail] = useState("");
  const [newUserRole, setNewUserRole] = useState<"employee" | "admin">("employee");
  const [newUserBusy, setNewUserBusy] = useState(false);
  const [newUserTempPassword, setNewUserTempPassword] = useState("");
  const [resetBusy, setResetBusy] = useState(false);
  const [resetTempPassword, setResetTempPassword] = useState("");
  const [tempPasswordModalOpen, setTempPasswordModalOpen] = useState(false);

  async function copy(text: string) {
    const t = String(text ?? "");
    try {
      await navigator.clipboard.writeText(t);
      return;
    } catch {
      // ignore
    }
    try {
      const el = document.createElement("textarea");
      el.value = t;
      el.style.position = "fixed";
      el.style.left = "-9999px";
      el.style.top = "-9999px";
      document.body.appendChild(el);
      el.focus();
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
    } catch {
      // ignore
    }
  }
  const closeTempPasswordModal = () => {
    setTempPasswordModalOpen(false);
    setNewUserTempPassword("");
    setResetTempPassword("");
  };

  // Import
  const [importFiles, setImportFiles] = useState<File[]>([]);
  const [importBusy, setImportBusy] = useState(false);
  const [importBatch, setImportBatch] = useState<{ total: number; done: number } | null>(null);
  const [importEnqueueProgress, setImportEnqueueProgress] = useState<{ total: number; done: number } | null>(null);
  const [clientImportStage, setClientImportStage] = useState<string>("");
  const [clientImportFileName, setClientImportFileName] = useState<string>("");
  const [importPendingCount, setImportPendingCount] = useState<number>(0);
  const [importPendingNames, setImportPendingNames] = useState<string[]>([]);
  const [importQueue, setImportQueue] = useState<ImportJobItem[]>([]);
  const [importQueueLoading, setImportQueueLoading] = useState(false);
  const [importQueueWorkers, setImportQueueWorkers] = useState<number>(0);
  const [importQueueHistory, setImportQueueHistory] = useState<ImportJobItem[]>([]);
  const [importQueueView, setImportQueueView] = useState<"active" | "history">("active");
  const [importQueueModalOpen, setImportQueueModalOpen] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState<string>("");
  const [jobStatus, setJobStatus] = useState<string>("");
  const [jobResult, setJobResult] = useState<any>(null);
  const [jobStage, setJobStage] = useState<string>("");
  const [jobStageAt, setJobStageAt] = useState<string>("");
  const [jobStageStartedAt, setJobStageStartedAt] = useState<string>("");
  const [jobStageDurations, setJobStageDurations] = useState<Record<string, number> | null>(null);
  const [jobStartedAt, setJobStartedAt] = useState<string>("");
  const [jobDetail, setJobDetail] = useState<string>("");
  const [jobError, setJobError] = useState<string>("");
  const [jobErrorCode, setJobErrorCode] = useState<string>("");
  const [jobErrorHint, setJobErrorHint] = useState<string>("");
  const [jobKind, setJobKind] = useState<string>("");
  const [jobModuleTitle, setJobModuleTitle] = useState<string>("");
  const [jobModuleId, setJobModuleId] = useState<string>("");
  const [jobPanelOpen, setJobPanelOpen] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [jobsSseConnected, setJobsSseConnected] = useState(false);
  const [s3UploadProgress, setS3UploadProgress] = useState<any>(null);
  const [uploadHistory, setUploadHistory] = useState<any[]>([]);

  // Diagnostics
  const [sys, setSys] = useState<any>(null);
  const [sysLoading, setSysLoading] = useState(false);
  const [diagSaving, setDiagSaving] = useState(false);
  const [openrouterEnabledDraft, setOpenrouterEnabledDraft] = useState<boolean>(false);
  const [openrouterBaseUrlDraft, setOpenrouterBaseUrlDraft] = useState<string>("");
  const [openrouterModelDraft, setOpenrouterModelDraft] = useState<string>("");
  const [openrouterApiKeyDraft, setOpenrouterApiKeyDraft] = useState<string>("");
  const [openrouterApiKeyMasked, setOpenrouterApiKeyMasked] = useState<string>("");
  const [openrouterHttpRefererDraft, setOpenrouterHttpRefererDraft] = useState<string>("");
  const [openrouterAppTitleDraft, setOpenrouterAppTitleDraft] = useState<string>("");
  const [llmEffective, setLlmEffective] = useState<any>(null);

  const [s3Draft, setS3Draft] = useState<any>({
    s3_endpoint_url: "",
    s3_public_endpoint_url: "",
    s3_access_key_id: "",
    s3_secret_access_key: "",
    s3_bucket: "",
    s3_region_name: "",
    s3_addressing_style: "",
    s3_access_key_id_masked: "",
    s3_secret_access_key_masked: "",
  });
  const [brokenModulesBusy, setBrokenModulesBusy] = useState(false);
  const [brokenModules, setBrokenModules] = useState<{ id: string; title: string }[]>([]);
  const [brokenModulesCount, setBrokenModulesCount] = useState<number>(0);

  // Storage
  const [storageUploads, setStorageUploads] = useState<StorageObjectItem[]>([]);
  const [storageUploadsLoading, setStorageUploadsLoading] = useState(false);
  const [storageUploadsPrefix, setStorageUploadsPrefix] = useState("uploads/");
  const [storageUploadsDebug, setStorageUploadsDebug] = useState<any>(null);
  const [isStorageScanning, setIsStorageScanning] = useState(false);
  const [storageOrphansCount, setStorageOrphansCount] = useState(0);
  const [modulesStorageScan, setModulesStorageScan] = useState<any[]>([]);
  const [modulesStorageScanBusy, setModulesStorageScanBusy] = useState(false);

  // Regen History
  const [regenHistory, setRegenHistory] = useState<any[]>([]);
  const [regenHistoryLoading, setRegenHistoryLoading] = useState(false);
  const [regenQueueModalOpen, setRegenQueueModalOpen] = useState(false);
  const [regenQueueWorkers, setRegenQueueWorkers] = useState<number>(0);

  // Analytics
  const [modules, setModules] = useState<Module[]>([]);
  const [moduleId, setModuleId] = useState<string>("");

  // --- Helper Functions ---
  const isTerminalJobLike = (it: any) => {
    const st = String((it as any)?.status || "").trim().toLowerCase();
    const stage = String((it as any)?.stage || "").trim().toLowerCase();
    return st === "finished" || st === "failed" || st === "canceled" || st === "missing" || stage === "canceled" || stage === "done" || stage === "missing";
  };

  const mergeOptimisticRegen = (prev: any[], incoming: any[]) => {
    const xs = Array.isArray(incoming) ? incoming : [];
    const seen = new Set<string>();
    for (const it of xs) {
      const jid = String((it as any)?.job_id || (it as any)?.id || "").trim();
      if (jid) seen.add(jid);
    }
    const keep: any[] = [];
    const now = Date.now();
    for (const p of Array.isArray(prev) ? prev : []) {
      if (!(p as any)?.optimistic) continue;
      const jid = String((p as any)?.job_id || (p as any)?.id || "").trim();
      if (!jid || seen.has(jid)) continue;
      const createdAt = String((p as any)?.created_at || "").trim();
      const t = createdAt ? Date.parse(createdAt) : 0;
      if (t && Number.isFinite(t) && now - t > 2 * 60 * 1000) continue;
      const stl = String((p as any)?.status || "").trim().toLowerCase();
      const stagel = String((p as any)?.stage || "").trim().toLowerCase();
      const terminal = stl === "missing" || stl === "finished" || stl === "failed" || stl === "canceled" || stagel === "canceled" || stagel === "done" || stagel === "missing";
      if (terminal) continue;
      keep.push(p);
    }
    return keep.length ? [...keep, ...xs] : xs;
  };

  const mergeRegenSnapshots = (prev: any[], incoming: any[]) => {
    const xs = Array.isArray(incoming) ? incoming : [];
    const byId = new Map<string, any>();

    const isStartedLike = (it: any): boolean => {
      const st = String((it as any)?.status || "").trim().toLowerCase();
      return st === "started";
    };

    const isPendingLike = (it: any): boolean => {
      const st = String((it as any)?.status || "").trim().toLowerCase();
      return st === "queued" || st === "deferred" || st === "scheduled";
    };

    for (const it of xs) {
      const jid = String((it as any)?.job_id || (it as any)?.id || "").trim();
      if (!jid) continue;
      byId.set(jid, it);
    }

    // Prevent "jobs overwrite each other" flicker:
    // if backend temporarily omits one active regen job from the snapshot,
    // keep the previous non-terminal job for a short time.
    const now = Date.now();
    for (const p of Array.isArray(prev) ? prev : []) {
      const jid = String((p as any)?.job_id || (p as any)?.id || "").trim();
      if (!jid || byId.has(jid)) continue;
      const terminal = isTerminalJobLike(p);

      // If a job was only pending in queue and it disappears from the authoritative snapshot,
      // drop it immediately (otherwise it looks like the UI is stale until refresh).
      if (!terminal && isPendingLike(p) && (!isStartedLike(p))) continue;

      // Keep terminal jobs briefly even if backend temporarily omits history between transitions.
      if (terminal) {
        const stageAt = String((p as any)?.stage_at || (p as any)?.created_at || "").trim();
        const tParsed = stageAt ? Date.parse(stageAt) : 0;
        const tSeen = Number((p as any)?._client_seen_at || 0);
        const t = (tParsed && Number.isFinite(tParsed)) ? tParsed : (tSeen || 0);
        if (t && Number.isFinite(t) && now - t <= 2 * 60 * 1000) {
          byId.set(jid, p);
        }
        continue;
      }

      // Only retain missing jobs briefly if they were started.
      if (!isStartedLike(p)) continue;

      const stageAt = String((p as any)?.stage_at || (p as any)?.created_at || "").trim();
      const tParsed = stageAt ? Date.parse(stageAt) : 0;
      const tSeen = Number((p as any)?._client_seen_at || 0);
      const t = (tParsed && Number.isFinite(tParsed)) ? tParsed : (tSeen || 0);
      if (t && Number.isFinite(t) && now - t > 2 * 60 * 1000) continue;
      byId.set(jid, p);
    }

    const merged = Array.from(byId.values());
    return mergeOptimisticRegen(prev, merged);
  };

  const mergeImportSnapshots = (prev: any[], incoming: any[]) => {
    const xs = Array.isArray(incoming) ? incoming : [];
    const byId = new Map<string, any>();

    const isStartedLike = (it: any): boolean => {
      const st = String((it as any)?.status || "").trim().toLowerCase();
      const stage = String((it as any)?.stage || "").trim().toLowerCase();
      return st === "started" || stage === "started";
    };

    const isPendingLike = (it: any): boolean => {
      const st = String((it as any)?.status || "").trim().toLowerCase();
      const stage = String((it as any)?.stage || "").trim().toLowerCase();
      return st === "queued" || st === "deferred" || st === "scheduled" || stage === "queued" || stage === "deferred" || stage === "scheduled";
    };

    for (const it of xs) {
      const jid = String((it as any)?.job_id || (it as any)?.id || "").trim();
      if (!jid) continue;
      byId.set(jid, it);
    }

    const now = Date.now();
    for (const p of Array.isArray(prev) ? prev : []) {
      const jid = String((p as any)?.job_id || (p as any)?.id || "").trim();
      if (!jid || byId.has(jid)) continue;
      if (isTerminalJobLike(p)) continue;

      // Pending queue items must disappear immediately when not present in the authoritative snapshot.
      // Otherwise the UI looks stale until refresh.
      if (isPendingLike(p) && (!isStartedLike(p))) continue;

      // Only retain briefly if it was started (anti-flicker for active jobs).
      if (!isStartedLike(p)) continue;

      const stageAt = String((p as any)?.stage_at || (p as any)?.created_at || "").trim();
      const t = stageAt ? Date.parse(stageAt) : 0;
      if (t && Number.isFinite(t) && now - t > 2 * 60 * 1000) continue;
      byId.set(jid, p);
    }

    return Array.from(byId.values());
  };

  const hasStartedJobLike = (xs: any[]): boolean => {
    try {
      for (const it of Array.isArray(xs) ? xs : []) {
        const st = String((it as any)?.status || "").trim().toLowerCase();
        const stage = String((it as any)?.stage || "").trim().toLowerCase();
        if (st === "started" || stage === "started") return true;
      }
      return false;
    } catch {
      return false;
    }
  };

  const shouldIgnoreEmptySnapshot = (prev: any[], incoming: any[], kind: "import" | "regen", source: string): boolean => {
    try {
      const inc = Array.isArray(incoming) ? incoming : [];
      if (inc.length > 0) return false;

      const p = Array.isArray(prev) ? prev : [];
      if (!p.length) return false;

      // If we recently saw a started job, an empty snapshot is most likely transient.
      // Ignore it briefly to prevent UI from dropping the current job until refresh.
      const hasStarted = hasStartedJobLike(p);
      if (!hasStarted) return false;

      // Tight window: we only guard against short transient gaps.
      const now = Date.now();
      let newestSeenAt = 0;
      for (const it of p) {
        const tSeen = Number((it as any)?._client_seen_at || 0);
        if (tSeen && Number.isFinite(tSeen)) newestSeenAt = Math.max(newestSeenAt, tSeen);
      }
      if (newestSeenAt && now - newestSeenAt <= 25_000) {
        jobsLog("snapshot.empty_ignored", { kind, source, prev: p.length });
        return true;
      }
      return false;
    } catch {
      return false;
    }
  };

  const s3Label = useMemo(() => {
    const p = s3UploadProgress;
    if (!p) return null;
    const humanBytesLocal = (n: number): string => {
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
    const speed = typeof p.speedBps === 'number' ? `${(p.speedBps / (1024 * 1024)).toFixed(1)} MB/s` : "—";
    const eta = typeof p.etaSeconds === "number" ? `${p.etaSeconds}s` : "—";
    return {
      percent: p.percent || 0,
      loadedHuman: humanBytesLocal(p.loaded || 0),
      totalHuman: humanBytesLocal(p.total || 0),
      speed,
      eta,
    };
  }, [s3UploadProgress]);

  const regenQueue = useMemo(() => {
    const items: RegenJobItem[] = [];
    const seen = new Set<string>();
    for (const it of regenHistory || []) {
      const jid = String((it as any)?.job_id || (it as any)?.id || "").trim();
      if (!jid) continue;
      if (seen.has(jid)) continue;
      seen.add(jid);
      const st = String((it as any)?.status || "").trim().toLowerCase();
      const stage = String((it as any)?.stage || "").trim().toLowerCase();
      const terminal = st === "finished" || st === "failed" || st === "canceled" || stage === "canceled" || stage === "done";
      if (terminal) continue;
      items.push({
        job_id: jid,
        module_id: (it as any).module_id,
        module_title: (it as any).module_title,
        submodule_id: (it as any).submodule_id,
        submodule_title: (it as any).submodule_title,
        status: st,
        stage: stage,
        created_at: (it as any).created_at,
        stage_at: (it as any).stage_at,
        detail: (it as any).detail,
        error: (it as any).error || (it as any).error_message,
        error_code: (it as any).error_code,
        error_hint: (it as any).error_hint,
        error_message: (it as any).error_message,
        queue: (it as any).queue,
      });
    }
    return items;
  }, [regenHistory]);

  function clearCurrentJobPanelState() {
    setSelectedJobId("");
    setJobStatus("");
    setJobStage("");
    setJobStageAt("");
    setJobStageStartedAt("");
    setJobStageDurations(null);
    setJobStartedAt("");
    setJobDetail("");
    setJobError("");
    setJobErrorCode("");
    setJobErrorHint("");
    setJobKind("");
    setJobModuleTitle("");
    setJobModuleId("");
    setJobResult(null);
  }

  const applyJobPanelSnapshot = (snap: any, source: string) => {
    try {
      if (!snap) return;
      const id = String((snap as any)?.id || (snap as any)?.job_id || "").trim();
      if (!id) return;
      if (id !== String(selectedJobIdRef.current || "").trim()) return;

      const st = String((snap as any)?.status || "").trim();
      const stage = String((snap as any)?.stage || "").trim();
      const stageAt = String((snap as any)?.stage_at || "").trim();
      const stageStartedAt = String((snap as any)?.stage_started_at || "").trim();
      const jobStartedAt = String((snap as any)?.job_started_at || (snap as any)?.started_at || "").trim();
      const detail = String((snap as any)?.detail || "").trim();
      const errorMessage = String((snap as any)?.error_message || (snap as any)?.error || "").trim();
      const errorCode = String((snap as any)?.error_code || "").trim();
      const errorHint = String((snap as any)?.error_hint || "").trim();
      const kind = String((snap as any)?.job_kind || "").trim();
      const moduleTitle = String((snap as any)?.module_title || "").trim();
      const moduleId = String((snap as any)?.module_id || "").trim();
      const durations = (snap as any)?.stage_durations_s;
      const result = (snap as any)?.result ?? null;

      setJobStatus(st);
      setJobStage(stage);
      setJobStageAt(stageAt);
      setJobStageStartedAt(stageStartedAt);
      setJobStartedAt(jobStartedAt);
      setJobDetail(detail);
      setJobError(errorMessage);
      setJobErrorCode(errorCode);
      setJobErrorHint(errorHint);
      setJobKind(kind);
      setJobModuleTitle(moduleTitle);
      setJobModuleId(moduleId);
      if (durations && typeof durations === "object") setJobStageDurations(durations);
      if (result !== undefined) setJobResult(result);

      jobsLog("panel.apply", {
        source,
        id,
        status: st,
        stage,
        hasDetail: Boolean(detail),
        hasError: Boolean(errorMessage),
      });
    } catch {
      // ignore
    }
  };

  const hydrateJobPanel = async (jobId: string, reason: string) => {
    const id = String(jobId || "").trim();
    if (!id) return;
    try {
      const now = Date.now();
      const st = jobPanelHydrateRef.current;
      if (st.jobId === id && now - (st.lastAtMs || 0) < 1200) return;
      jobPanelHydrateRef.current = { jobId: id, lastAtMs: now };
      jobsLog("panel.hydrate", { id, reason });
      const snap = await apiFetch<any>(`/admin/jobs/${encodeURIComponent(id)}`);
      applyJobPanelSnapshot({ id, ...(snap as any) }, "api");
    } catch {
      // ignore
    }
  };

  function hasActiveCurrentJob(): boolean {
    const jid = String(selectedJobId || "").trim();
    if (!jid) return false;
    const st = String(jobStatus || "").trim().toLowerCase();
    const stage = String(jobStage || "").trim().toLowerCase();
    if (!st) return true;
    if (st === "finished" || st === "failed" || st === "missing" || st === "canceled") return false;
    if (stage === "canceled" || stage === "done" || stage === "missing") return false;
    return true;
  }

  // --- API Functions ---
  async function loadRegenHistory(silent = false) {
    try {
      if (!silent) setRegenHistoryLoading(true);
      const res = await apiFetch<{ items: any[]; history?: any[]; workers?: number }>(`/admin/regen-jobs?limit=200&include_terminal=true`);
      try {
        setRegenQueueWorkers(Number((res as any)?.workers || 0));
      } catch {
        setRegenQueueWorkers(0);
      }

      const now = Date.now();
      const normItems = (res?.items || []).map((x) => ({ _client_seen_at: now, job_id: String((x as any)?.job_id || (x as any)?.id || ""), ...x }));
      const normHist = (res?.history || []).map((x) => ({ _client_seen_at: now, job_id: String((x as any)?.job_id || (x as any)?.id || ""), ...x }));
      const next = normItems.concat(normHist);
      jobsLog("poll.regen", {
        items: normItems.length,
        history: normHist.length,
        total: next.length,
        workers: Number((res as any)?.workers || 0),
      });
      if (JSON.stringify(next) !== regenHistorySigRef.current) {
        setRegenHistory((prev: any[]) => {
          if (shouldIgnoreEmptySnapshot(prev, next, "regen", "poll")) return prev;
          regenHistorySigRef.current = JSON.stringify(next);
          return mergeRegenSnapshots(prev, next);
        });
      }
    } catch {
      // Keep last known snapshot to avoid UI flicker (queues temporarily disappearing).
      // Backend/SSE can be transiently unavailable.
    } finally {
      if (!silent) setRegenHistoryLoading(false);
    }
  }

  async function loadImportQueue(limit = 20, includeTerminal = false, silent = false) {
    try {
      if (!silent) setImportQueueLoading(true);
      const res = await apiFetch<{ items: any[]; history?: any[]; workers?: number }>(`/admin/import-jobs?limit=${limit}&include_terminal=${includeTerminal}`);
      try {
        setImportQueueWorkers(Number((res as any)?.workers || 0));
      } catch {
        setImportQueueWorkers(0);
      }

      const now = Date.now();
      const items = (res?.items || []).map((x) => ({ _client_seen_at: now, job_id: String((x as any)?.job_id || (x as any)?.id || ""), ...x }));
      const hist = (res?.history || []).map((x) => ({ _client_seen_at: now, job_id: String((x as any)?.job_id || (x as any)?.id || ""), ...x }));

      // If a job is already terminal in history, it must not remain in the active snapshot
      // (otherwise mergeImportSnapshots may retain an outdated 'started' entry and the UI looks stale).
      const terminalIds = new Set<string>();
      try {
        for (const h of hist) {
          const jid = String((h as any)?.job_id || (h as any)?.id || "").trim();
          if (!jid) continue;
          if (isTerminalJobLike(h)) terminalIds.add(jid);
        }
      } catch {
        // ignore
      }
      const filteredItems = terminalIds.size
        ? items.filter((it) => {
            const jid = String((it as any)?.job_id || (it as any)?.id || "").trim();
            if (!jid) return true;
            return !terminalIds.has(jid);
          })
        : items;

      jobsLog("poll.import", {
        items: items.length,
        history: hist.length,
        limit,
        includeTerminal,
        workers: Number((res as any)?.workers || 0),
      });

      if (JSON.stringify(filteredItems) !== importQueueSigRef.current) {
        setImportQueue((prev: any[]) => {
          if (shouldIgnoreEmptySnapshot(prev, filteredItems, "import", "poll.items")) return prev;
          importQueueSigRef.current = JSON.stringify(filteredItems);
          return mergeImportSnapshots(prev, filteredItems);
        });
      }
      if (JSON.stringify(hist) !== importQueueHistorySigRef.current) {
        setImportQueueHistory((prev: any[]) => {
          if (shouldIgnoreEmptySnapshot(prev, hist, "import", "poll.history")) return prev;
          importQueueHistorySigRef.current = JSON.stringify(hist);
          return mergeImportSnapshots(prev, hist);
        });
      }
    } catch {
      // Keep last known snapshot to avoid UI flicker (queues temporarily disappearing).
    } finally {
      if (!silent) setImportQueueLoading(false);
    }
  }

  const applyJobsModel = (payload: any, source: string) => {
    try {
      const impLane = (payload as any)?.import || {};
      const rgLane = (payload as any)?.regen || {};

      const now = Date.now();

      const impCurrent = (impLane as any)?.current && typeof (impLane as any)?.current === "object" ? (impLane as any).current : null;
      const impQueue = Array.isArray((impLane as any)?.queue) ? (impLane as any).queue : [];
      const impHist = Array.isArray((impLane as any)?.history) ? (impLane as any).history : [];
      const impItems = (impCurrent ? [impCurrent] : []).concat(impQueue).map((x: any) => ({ _client_seen_at: now, job_id: String((x as any)?.job_id || (x as any)?.id || ""), ...x }));
      const impHistory = impHist.map((x: any) => ({ _client_seen_at: now, job_id: String((x as any)?.job_id || (x as any)?.id || ""), ...x }));

      // Prevent stale 'started' import job from being retained in active queue when it is already terminal in history.
      const importTerminalIds = new Set<string>();
      try {
        for (const h of impHistory) {
          const jid = String((h as any)?.job_id || (h as any)?.id || "").trim();
          if (!jid) continue;
          if (isTerminalJobLike(h)) importTerminalIds.add(jid);
        }
      } catch {
        // ignore
      }
      const impItemsFiltered = importTerminalIds.size
        ? impItems.filter((it: any) => {
            const jid = String((it as any)?.job_id || (it as any)?.id || "").trim();
            if (!jid) return true;
            return !importTerminalIds.has(jid);
          })
        : impItems;

      try {
        setImportQueueWorkers(Number((impLane as any)?.workers || 0));
      } catch {
        setImportQueueWorkers(0);
      }

      jobsLog("model.apply", {
        source,
        rev: Number((payload as any)?.rev || 0) || 0,
        import_queue: impQueue.length,
        import_current: Boolean(impCurrent),
        import_history: impHist.length,
        regen_queue: Array.isArray((rgLane as any)?.queue) ? (rgLane as any).queue.length : 0,
        regen_current: Boolean((rgLane as any)?.current),
        regen_history: Array.isArray((rgLane as any)?.history) ? (rgLane as any).history.length : 0,
      });

      if (JSON.stringify(impItemsFiltered) !== importQueueSigRef.current) {
        setImportQueue((prev: any[]) => {
          if (shouldIgnoreEmptySnapshot(prev, impItemsFiltered, "import", `${source}.import.queue_current`)) return prev;
          importQueueSigRef.current = JSON.stringify(impItemsFiltered);
          return mergeImportSnapshots(prev, impItemsFiltered);
        });
      }
      if (JSON.stringify(impHistory) !== importQueueHistorySigRef.current) {
        setImportQueueHistory((prev: any[]) => {
          if (shouldIgnoreEmptySnapshot(prev, impHistory, "import", `${source}.import.history`)) return prev;
          importQueueHistorySigRef.current = JSON.stringify(impHistory);
          return mergeImportSnapshots(prev, impHistory);
        });
      }

      // Regen lane: keep a single merged list for current queue + history.
      const rgCurrent = (rgLane as any)?.current && typeof (rgLane as any)?.current === "object" ? (rgLane as any).current : null;
      const rgQueue = Array.isArray((rgLane as any)?.queue) ? (rgLane as any).queue : [];
      const rgHist = Array.isArray((rgLane as any)?.history) ? (rgLane as any).history : [];
      const rgAll = (rgCurrent ? [rgCurrent] : []).concat(rgQueue).concat(rgHist).map((x: any) => ({ _client_seen_at: now, job_id: String((x as any)?.job_id || (x as any)?.id || ""), ...x }));

      try {
        setRegenQueueWorkers(Number((rgLane as any)?.workers || 0));
      } catch {
        setRegenQueueWorkers(0);
      }

      if (JSON.stringify(rgAll) !== regenHistorySigRef.current) {
        setRegenHistory((prev: any[]) => {
          if (shouldIgnoreEmptySnapshot(prev, rgAll, "regen", `${source}.regen.all`)) return prev;
          regenHistorySigRef.current = JSON.stringify(rgAll);
          return mergeRegenSnapshots(prev, rgAll);
        });
      }

      // Opportunistically refresh the job detail panel from the lane payload.
      try {
        const sel = String(selectedJobIdRef.current || "").trim();
        if (sel) {
          const found = impItems.concat(impHistory).concat(rgAll).find((x: any) => String((x as any)?.job_id || (x as any)?.id || "").trim() === sel);
          if (found) applyJobPanelSnapshot({ id: sel, ...(found as any) }, `${source}.panel`);
        }
      } catch {
        // ignore
      }
    } catch {
      // ignore
    }
  };

  const loadJobsModel = async (silent = true) => {
    try {
      const payload = await apiFetch<any>(`/admin/jobs/model`);
      applyJobsModel(payload, "poll.model");
    } catch {
      // ignore
    }
  };

  async function startImport() {
    if (importFiles.length === 0) return;
    if (importRunnerActiveRef.current) return;

    importRunnerActiveRef.current = true;
    importUploadAbortRef.current = new AbortController();

    const batch = Array.from(importFiles);
    importQueuePendingRef.current = batch;
    setImportPendingCount(batch.length);
    setImportPendingNames(batch.map((f) => String((f as any)?.name || "").trim()).filter(Boolean));
    setImportEnqueueProgress({ total: batch.length, done: 0 });
    goTab("import");
    setJobPanelOpen(true);
    setImportBusy(true);

    try {
      for (let i = 0; i < batch.length; i++) {
        const f = batch[i];
        const fn = String((f as any)?.name || "module.zip").trim() || "module.zip";

        setClientImportFileName(fn);
        setClientImportStage("upload");

        const fd = new FormData();
        fd.append("file", f as unknown as Blob, fn);

        // Title is optional; backend will infer from filename if not provided.
        const res = await apiFetch<{ ok: boolean; job_id: string; module_id?: string | null }>(
          `/admin/modules/import-zip`,
          {
            method: "POST",
            body: fd as any,
            signal: importUploadAbortRef.current?.signal,
          } as any
        );

        const jid = String((res as any)?.job_id || "").trim();
        if (jid) {
          try {
            const hasStartedImport = (importQueue || []).some((x: any) => String(x?.status || "").trim().toLowerCase() === "started");
            if (!hasStartedImport) {
              setSelectedJobId(jid);
              setJobStatus("queued");
            }
          } catch {
            setSelectedJobId(jid);
            setJobStatus("queued");
          }
        }

        // Product UX: newly imported module should appear immediately (stub module is created in backend).
        // Keep UI stable: do not reload public modules list automatically; rely on SSE + admin modules refresh.
        void loadAdminModulesForce();

        setImportEnqueueProgress({ total: batch.length, done: i + 1 });
        setImportPendingCount(Math.max(0, batch.length - (i + 1)));
        setImportPendingNames(batch.slice(i + 1).map((x) => String((x as any)?.name || "").trim()).filter(Boolean));

        // Keep admin queue fresh.
        void loadImportQueue(50, true, true);
      }

      setClientImportStage("done");
      setImportFiles([]);
    } catch (e) {
      if ((e as any)?.name === "AbortError") {
        setClientImportStage("canceled");
      } else {
        setClientImportStage("failed");
        setError(e instanceof Error ? e.message : "НЕ УДАЛОСЬ ИМПОРТИРОВАТЬ ZIP");
      }
    } finally {
      importRunnerActiveRef.current = false;
      importQueuePendingRef.current = [];
      setImportBusy(false);
      setImportEnqueueProgress(null);
      setImportPendingCount(0);
      setImportPendingNames([]);
      try {
        importUploadAbortRef.current = null;
      } catch {
        // ignore
      }
    }
  }

  async function cancelActiveUpload() {
    try {
      importCancelRequestedRef.current = true;
      importUploadAbortRef.current?.abort();
    } catch {
      // ignore
    } finally {
      setClientImportStage("canceled");
      setImportBusy(false);
    }
  }

  async function enqueueImportFromS3(objectKey: string) {
    const object_key = String(objectKey || "").trim();
    if (!object_key) return;
    setTab("import");
    setJobPanelOpen(true);
    try {
      const inferredName = object_key.split("/").slice(-1)[0] || "module.zip";
      const enq = await apiFetch<{ ok: boolean; job_id: string }>(`/admin/modules/enqueue-import-zip`, {
        method: "POST",
        body: JSON.stringify({ object_key, title: null, source_filename: inferredName }),
      });
      const jid = String((enq as any)?.job_id || "").trim();
      if (jid) {
        try {
          const hasStartedImport = (importQueue || []).some((x: any) => String(x?.status || "").trim().toLowerCase() === "started");
          if (!hasStartedImport) {
            setSelectedJobId(jid);
            setJobStatus("queued");
          }
        } catch {
          setSelectedJobId(jid);
          setJobStatus("queued");
        }
        void loadJobsModel(true);
        void loadStorageUploads(storageUploadsPrefix);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка постановки в очередь");
    }
  }

  async function retryImportJob(id: string) {
    try {
      await apiFetch(`/admin/import-jobs/${encodeURIComponent(id)}/retry`, { method: "POST" });
      void loadJobsModel(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка повтора");
    }
  }

  async function cancelImportJob(id: string) {
    try {
      setCancelBusy(true);
      await apiFetch(`/admin/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
      void loadJobsModel(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка отмены");
    } finally {
      setCancelBusy(false);
    }
  }

  async function cancelRegenJob(id: string) {
    try {
      setCancelBusy(true);
      await apiFetch(`/admin/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
      void loadJobsModel(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка отмены");
    } finally {
      setCancelBusy(false);
    }
  }

  async function clearAdminJobHistory() {
    try {
      await apiFetch(`/admin/jobs/history/clear`, { method: "POST" });
      await loadJobsModel(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка очистки");
    }
  }

  function openModuleFromImport(it: ImportJobItem) {
    if (it.module_id) {
      setSelectedAdminModuleId(it.module_id);
      goTab("modules");
    }
  }

  function cancelCurrentJob() {
    if (selectedJobId) void cancelImportJob(selectedJobId);
  }

  async function loadUsers() {
    const now = Date.now();
    if (now - Number(usersLoadedAtRef.current || 0) < ADMIN_CACHE_TTL_MS) return;
    try {
      setUsersLoading(true);
      const res = await apiFetch<{ items: UserItem[] }>(`/admin/users`);
      const items = Array.isArray(res?.items) ? res.items : [];
      setUsers(items);
      usersLoadedAtRef.current = Date.now();
      if (items.length && (!selectedUserId || !items.some((u) => String(u.id) === String(selectedUserId)))) {
        setSelectedUserId(String(items[0].id));
      }
    } catch {
      setUsers([]);
    } finally {
      setUsersLoading(false);
    }
  }

  async function loadUsersForce() {
    usersLoadedAtRef.current = 0;
    await loadUsers();
  }

  async function loadUserDetail(userId: string) {
    const id = String(userId || "").trim();
    if (!id) {
      setUserDetail(null);
      return;
    }
    try {
      setUserDetailLoading(true);
      const res = await apiFetch<UserDetail>(`/admin/users/${encodeURIComponent(id)}`);
      setUserDetail(res || null);
    } catch {
      setUserDetail(null);
    } finally {
      setUserDetailLoading(false);
    }

    try {
      setUserHistoryLoading(true);
      const hist = await apiFetch<{ items: UserHistoryDetailedItem[] }>(
        `/admin/users/${encodeURIComponent(id)}/history?limit=500`
      );
      setUserHistoryDetailed(Array.isArray(hist?.items) ? hist.items : []);
    } catch {
      setUserHistoryDetailed([]);
    } finally {
      setUserHistoryLoading(false);
    }
  }

  async function createUser() {
    const nm = String(newUserName || "").trim();
    const em = String(newUserEmail || "").trim();
    if (!em) {
      setError("EMAIL ОБЯЗАТЕЛЕН ДЛЯ ВХОДА");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(em)) {
      setError("НЕВЕРНЫЙ ФОРМАТ EMAIL");
      return;
    }
    try {
      setNewUserBusy(true);
      setError(null);
      const res = await apiFetch<{ id: string; temp_password?: string | null }>(`/admin/users`, {
        method: "POST",
        body: JSON.stringify({
          name: nm || em.split("@", 1)[0] || em,
          email: em,
          role: newUserRole,
          must_change_password: true,
        }),
      });
      setResetTempPassword("");
      setNewUserTempPassword(res.temp_password || "");
      setTempPasswordModalOpen(true);
      setNewUserName("");
      setNewUserEmail("");
      usersLoadedAtRef.current = 0;
      await loadUsers();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      const m = String(msg || "").toLowerCase();
      if (m.includes("duplicate") || m.includes("already") || m.includes("exists")) {
        setError("ПОЛЬЗОВАТЕЛЬ С ТАКИМ EMAIL УЖЕ ЕСТЬ");
      } else if (m.includes("user email already exists")) {
        setError("EMAIL УЖЕ ЗАНЯТ");
      } else if (m.includes("user already exists")) {
        setError("ПОЛЬЗОВАТЕЛЬ УЖЕ СУЩЕСТВУЕТ");
      } else {
        setError(msg || "НЕ УДАЛОСЬ СОЗДАТЬ ПОЛЬЗОВАТЕЛЯ");
      }
    } finally {
      setNewUserBusy(false);
    }
  }

  async function resetPassword() {
    if (!selectedUserId) return;
    try {
      setResetBusy(true);
      setError(null);
      const res = await apiFetch<{ ok: boolean; temp_password?: string | null }>(
        `/admin/users/${encodeURIComponent(selectedUserId)}/reset-password`,
        {
          method: "POST",
          body: JSON.stringify({ must_change_password: true }),
        }
      );
      setNewUserTempPassword("");
      setResetTempPassword(res?.temp_password || "");
      setTempPasswordModalOpen(true);
      void loadUserDetail(selectedUserId);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ СБРОСИТЬ ПАРОЛЬ");
    } finally {
      setResetBusy(false);
    }
  }

  async function deleteSelectedUser() {
    if (!selectedUserId) return;
    const ok = window.confirm("Удалить пользователя? Действие необратимо.");
    if (!ok) return;
    try {
      setDeleteUserBusy(true);
      setError(null);
      await apiFetch<any>(`/admin/users/${encodeURIComponent(selectedUserId)}`, { method: "DELETE" });
      window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "ПОЛЬЗОВАТЕЛЬ УДАЛЁН", description: "" } }));
      setSelectedUserId("");
      setUserDetail(null);
      await loadUsersForce();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ УДАЛИТЬ ПОЛЬЗОВАТЕЛЯ");
    } finally {
      setDeleteUserBusy(false);
    }
  }

  async function updateSelectedUser(patch: any) {
    if (!selectedUserId) return;
    try {
      setError(null);
      await apiFetch<any>(`/admin/users/${encodeURIComponent(selectedUserId)}`, { method: "PATCH", body: JSON.stringify(patch || {}) });
      await Promise.all([loadUsersForce(), loadUserDetail(selectedUserId)]);
      window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "ПОЛЬЗОВАТЕЛЬ ОБНОВЛЁН", description: "" } }));
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ ОБНОВИТЬ ПОЛЬЗОВАТЕЛЯ");
    }
  }

  async function forceSelectedUserPasswordChange() {
    if (!selectedUserId) return;
    if (!window.confirm("ЗАСТАВИТЬ ПОЛЬЗОВАТЕЛЯ СМЕНИТЬ ПАРОЛЬ ПРИ СЛЕДУЮЩЕМ ВХОДЕ?")) return;
    try {
      setError(null);
      await apiFetch<any>(`/admin/users/${encodeURIComponent(selectedUserId)}/force-password-change`, { method: "POST" });
      await loadUserDetail(selectedUserId);
      window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "ТРЕБУЕТСЯ СМЕНА ПАРОЛЯ", description: "" } }));
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ ВКЛЮЧИТЬ СМЕНУ ПАРОЛЯ");
    }
  }

  async function loadSystemStatus() {
    const now = Date.now();
    if (now - Number(systemStatusLoadedAtRef.current || 0) < ADMIN_CACHE_TTL_MS) return;
    try {
      setSysLoading(true);
      const res = await apiFetch<any>(`/admin/system/status`);
      setSys(res || null);
      systemStatusLoadedAtRef.current = Date.now();
    } catch {
      setSys(null);
    } finally {
      setSysLoading(false);
    }
  }

  async function loadSystemStatusForce() {
    systemStatusLoadedAtRef.current = 0;
    await loadSystemStatus();
  }

  async function loadAdminModules() {
    const now = Date.now();
    if (now - Number(adminModulesLoadedAtRef.current || 0) < ADMIN_CACHE_TTL_MS) return;
    try {
      setAdminModulesLoading(true);
      const res = await apiFetch<{ items: AdminModuleItem[] }>(`/admin/modules`);
      const items = (res?.items || []).map((m) => ({
        id: String(m.id),
        title: String(m.title || ""),
        is_active: !!(m as any).is_active,
        final_quiz_id: (m as any).final_quiz_id ? String((m as any).final_quiz_id) : null,
        category: (m as any).category ?? null,
        difficulty: typeof (m as any).difficulty === "number" ? (m as any).difficulty : null,
        import_object_key: (m as any).import_object_key ? String((m as any).import_object_key) : null,
        storage_prefix: (m as any).storage_prefix ? String((m as any).storage_prefix) : null,
        storage_ok: Boolean((m as any).storage_ok),
        question_quality: (m as any).question_quality && typeof (m as any).question_quality === "object" ? {
          total_current: Number((m as any).question_quality.total_current || 0),
          needs_regen_current: Number((m as any).question_quality.needs_regen_current || 0),
          fallback_current: Number((m as any).question_quality.fallback_current || 0),
          ai_current: Number((m as any).question_quality.ai_current || 0),
          heur_current: Number((m as any).question_quality.heur_current || 0),
        } : undefined,
      })).sort((a, b) => {
        if (a.is_active !== b.is_active) return a.is_active ? -1 : 1;
        return String(a.title || "").localeCompare(String(b.title || ""));
      });
      setAdminModules(items);
      adminModulesLoadedAtRef.current = Date.now();
      void loadStorageOrphansCount();
      if (items.length && (!selectedAdminModuleId || !items.some(x => x.id === selectedAdminModuleId))) {
        setSelectedAdminModuleId(items[0].id);
      }
    } finally {
      setAdminModulesLoading(false);
    }
  }

  async function loadAdminModulesForce() {
    adminModulesLoadedAtRef.current = 0;
    await loadAdminModules();
  }

  async function reconcileModulesStorage() {
    try {
      setError(null);
      const res = await apiFetch<any>(`/admin/modules/reconcile`, {
        method: "POST",
        body: JSON.stringify({ apply: true }),
      });
      const dbCount = Number((res as any)?.db_modules || 0);
      const s3Count = Number((res as any)?.s3_prefixes || 0);
      const created = Number((res as any)?.created || 0);
      const missing = Array.isArray((res as any)?.missing_in_storage) ? (res as any).missing_in_storage.length : 0;
      const orphan = Array.isArray((res as any)?.orphan_in_storage) ? (res as any).orphan_in_storage.length : 0;
      setError(`SYNC: DB=${dbCount}, S3=${s3Count}, created=${created}, missing=${missing}, orphan=${orphan}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "SYNC FAILED");
    } finally {
      void loadAdminModulesForce();
      try {
        void loadStorageUploads(storageUploadsPrefix);
      } catch {
        // ignore
      }
    }
  }

  async function loadSelectedAdminModule() {
    if (!selectedAdminModuleId) {
      setSelectedAdminModuleSubs([]);
      setSelectedSubmoduleId("");
      setSelectedQuizId("");
      return;
    }
    try {
      setSelectedAdminModuleSubsLoading(true);
      const subs = await apiFetch<AdminSubmoduleItem[]>(`/modules/${encodeURIComponent(selectedAdminModuleId)}/submodules`);
      const sorted = (subs || []).slice().sort((a, b) => Number(a.order || 0) - Number(b.order || 0));
      setSelectedAdminModuleSubs(sorted);
      if (sorted.length && (!selectedSubmoduleId || !sorted.some((s) => s.id === selectedSubmoduleId))) {
        const first = sorted[0];
        setSelectedSubmoduleId(first.id);
        setSelectedQuizId(first.requires_quiz !== false ? String(first.quiz_id || "") : "");
      }
      void loadSelectedAdminModuleSubQuality(String(selectedAdminModuleId));
    } finally {
      setSelectedAdminModuleSubsLoading(false);
    }
  }

  async function loadSelectedAdminModuleSubQuality(moduleId: string) {
    const mid = String(moduleId || "").trim();
    if (!mid) return;
    try {
      setSubQualityLoadingByModuleId((prev: Record<string, boolean>) => ({ ...prev, [mid]: true }));
      const res = await apiFetch<{ ok: boolean; items: AdminSubmoduleQualityItem[] }>(`/admin/modules/${encodeURIComponent(mid)}/submodules/quality`);
      setSubQualityByModuleId((prev: Record<string, AdminSubmoduleQualityItem[]>) => ({ ...prev, [mid]: res?.items || [] }));
    } catch {
      setSubQualityByModuleId((prev: Record<string, AdminSubmoduleQualityItem[]>) => ({ ...prev, [mid]: [] }));
    } finally {
      setSubQualityLoadingByModuleId((prev: Record<string, boolean>) => ({ ...prev, [mid]: false }));
    }
  }

  async function loadQuestionsForQuiz(quizId: string) {
    const qid = String(quizId || "").trim();
    if (!qid) return;
    if (questionsLoadingQuizId) return;
    try {
      setQuestionsLoadingQuizId(qid);
      const res = await apiFetch<{ ok: boolean; items: AdminQuestionItem[] }>(
        `/admin/quizzes/${encodeURIComponent(qid)}/questions`
      );
      setQuestionsByQuizId((prev: Record<string, AdminQuestionItem[]>) => ({ ...prev, [qid]: res?.items || [] }));
    } catch {
      setQuestionsByQuizId((prev: Record<string, AdminQuestionItem[]>) => ({ ...prev, [qid]: [] }));
    } finally {
      setQuestionsLoadingQuizId("");
    }
  }

  async function loadStorageOrphansCount() {
    try {
      const res = await apiFetch<{ orphans_count: number }>("/admin/maintenance/storage/orphan-module-prefixes?sample_keys=0");
      setStorageOrphansCount(res?.orphans_count || 0);
    } catch {
      setStorageOrphansCount(0);
    }
  }

  async function purgeOrphanStorage() {
    if (!window.confirm(`Вы уверены, что хотите удалить ${storageOrphansCount} неиспользуемых префиксов в хранилище?`)) return;
    try {
      setIsStorageScanning(true);
      await apiFetch("/admin/maintenance/storage/purge-orphan-module-prefixes?dry_run=false", { method: "POST" });
      await loadStorageOrphansCount();
      window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "ХРАНИЛИЩЕ ОЧИЩЕНО", description: "" } }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "НЕ УДАЛОСЬ ОЧИСТИТЬ ХРАНИЛИЩЕ");
    } finally {
      setIsStorageScanning(false);
    }
  }

  async function loadStorageUploads(prefixOverride?: string) {
    let pfx = prefixOverride ?? storageUploadsPrefix;
    try {
      setStorageUploadsLoading(true);
      const res = await apiFetch<{ items: any[] }>(`/admin/storage/objects?prefix=${encodeURIComponent(pfx)}&limit=200&suffix=.zip`);
      setStorageUploads(res?.items || []);
      setStorageUploadsPrefix(pfx);
    } catch (e) {
      setError(e instanceof Error ? e.message : "НЕ УДАЛОСЬ ЗАГРУЗИТЬ СПИСОК ИМПОРТА");
    } finally {
      setStorageUploadsLoading(false);
    }
  }

  async function loadRuntimeLlmSettings() {
    const now = Date.now();
    if (now - Number(runtimeLlmLoadedAtRef.current || 0) < ADMIN_CACHE_TTL_MS) return;
    try {
      const data = await apiFetch<any>("/admin/runtime/llm");
      setOpenrouterEnabledDraft(!!data?.openrouter_enabled);
      setOpenrouterBaseUrlDraft(data?.openrouter_base_url || "");
      setOpenrouterModelDraft(data?.openrouter_model || "");
      setOpenrouterApiKeyMasked(data?.openrouter_api_key_masked || "");
      setOpenrouterHttpRefererDraft(data?.openrouter_http_referer || "");
      setOpenrouterAppTitleDraft(data?.openrouter_app_title || "");
      setLlmEffective(data?.effective || null);
      runtimeLlmLoadedAtRef.current = Date.now();
    } catch {
      // ignore
    }
  }

  async function loadRuntimeLlmSettingsForce() {
    runtimeLlmLoadedAtRef.current = 0;
    await loadRuntimeLlmSettings();
  }

  async function saveRuntimeLlmSettings() {
    try {
      setDiagSaving(true);
      const body: any = {
        openrouter_enabled: openrouterEnabledDraft,
        openrouter_base_url: openrouterBaseUrlDraft,
        openrouter_model: openrouterModelDraft,
        openrouter_http_referer: openrouterHttpRefererDraft,
        openrouter_app_title: openrouterAppTitleDraft,
      };
      if (openrouterApiKeyDraft) body.openrouter_api_key = openrouterApiKeyDraft;
      await apiFetch("/admin/runtime/llm", { method: "POST", body: JSON.stringify(body) });
      await Promise.all([loadSystemStatusForce(), loadRuntimeLlmSettingsForce()]);
      window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "НАСТРОЙКИ СОХРАНЕНЫ", description: "" } }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "НЕ УДАЛОСЬ СОХРАНИТЬ НАСТРОЙКИ");
    } finally {
      setDiagSaving(false);
    }
  }

  async function resetRuntimeLlmSettings() {
    try {
      setDiagSaving(true);
      await apiFetch("/admin/runtime/llm/reset", { method: "POST" });
      await Promise.all([loadSystemStatusForce(), loadRuntimeLlmSettingsForce()]);
      window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "RUNTIME LLM СБРОШЕН", description: "" } }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "НЕ УДАЛОСЬ СБРОСИТЬ RUNTIME LLM");
    } finally {
      setDiagSaving(false);
    }
  }

  async function loadRuntimeS3Settings() {
    const now = Date.now();
    if (now - Number(runtimeS3LoadedAtRef.current || 0) < ADMIN_CACHE_TTL_MS) return;
    try {
      const data = await apiFetch<any>("/admin/runtime/s3");
      setS3Draft({
        s3_endpoint_url: data?.s3_endpoint_url || "",
        s3_public_endpoint_url: data?.s3_public_endpoint_url || "",
        s3_access_key_id: "",
        s3_secret_access_key: "",
        s3_bucket: data?.s3_bucket || "",
        s3_region_name: data?.s3_region_name || "",
        s3_addressing_style: data?.s3_addressing_style || "",
        s3_access_key_id_masked: data?.s3_access_key_id_masked || "",
        s3_secret_access_key_masked: data?.s3_secret_access_key_masked || "",
      });
      runtimeS3LoadedAtRef.current = Date.now();
    } catch {
      // ignore
    }
  }

  async function loadRuntimeS3SettingsForce() {
    runtimeS3LoadedAtRef.current = 0;
    await loadRuntimeS3Settings();
  }

  async function saveRuntimeS3Settings() {
    try {
      setDiagSaving(true);
      const body: any = {
        s3_endpoint_url: String(s3Draft?.s3_endpoint_url || "").trim(),
        s3_public_endpoint_url: String(s3Draft?.s3_public_endpoint_url || "").trim(),
        s3_bucket: String(s3Draft?.s3_bucket || "").trim(),
        s3_region_name: String(s3Draft?.s3_region_name || "").trim(),
        s3_addressing_style: String(s3Draft?.s3_addressing_style || "").trim(),
      };
      if (String(s3Draft?.s3_access_key_id || "").trim()) body.s3_access_key_id = String(s3Draft.s3_access_key_id).trim();
      if (String(s3Draft?.s3_secret_access_key || "").trim()) body.s3_secret_access_key = String(s3Draft.s3_secret_access_key).trim();
      await apiFetch("/admin/runtime/s3", { method: "POST", body: JSON.stringify(body) });
      await Promise.all([loadRuntimeS3SettingsForce(), loadSystemStatusForce()]);
      window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "S3 НАСТРОЙКИ СОХРАНЕНЫ", description: "" } }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "НЕ УДАЛОСЬ СОХРАНИТЬ S3 НАСТРОЙКИ");
    } finally {
      setDiagSaving(false);
    }
  }

  async function resetRuntimeS3Settings() {
    try {
      setDiagSaving(true);
      await apiFetch("/admin/runtime/s3/reset", { method: "POST" });
      await Promise.all([loadRuntimeS3SettingsForce(), loadSystemStatusForce()]);
      window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "RUNTIME S3 СБРОШЕН", description: "" } }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "НЕ УДАЛОСЬ СБРОСИТЬ RUNTIME S3");
    } finally {
      setDiagSaving(false);
    }
  }

  async function scanBrokenModules() {
    try {
      setBrokenModulesBusy(true);
      const res = await apiFetch<any>(`/admin/maintenance/modules/purge-missing-storage?dry_run=true`);
      setBrokenModules(res?.items || []);
      setBrokenModulesCount(res?.missing_count || 0);
    } finally {
      setBrokenModulesBusy(false);
    }
  }

  async function scanModulesStorage() {
    try {
      setModulesStorageScanBusy(true);
      const res = await apiFetch<any>(`/admin/maintenance/modules/storage-scan`);
      setModulesStorageScan(res?.items || []);
    } finally {
      setModulesStorageScanBusy(false);
    }
  }

  async function purgeBrokenModules() {
    if (!window.confirm(`Удалить ${brokenModulesCount} битых модулей?`)) return;
    try {
      setBrokenModulesBusy(true);
      await apiFetch(`/admin/maintenance/modules/purge-missing-storage?dry_run=false`, { method: "POST" });
      await Promise.all([scanBrokenModules(), loadAdminModulesForce()]);
    } finally {
      setBrokenModulesBusy(false);
    }
  }

  async function setSelectedModuleVisibility(nextActive: boolean) {
    if (!selectedAdminModuleId) return;
    try {
      await apiFetch(`/admin/modules/${encodeURIComponent(selectedAdminModuleId)}/visibility`, { method: "POST", body: JSON.stringify({ is_active: nextActive }) });
      await loadAdminModulesForce();
      void loadSelectedAdminModule();
    } catch (e) {
      setError(e instanceof Error ? e.message : "НЕ УДАЛОСЬ ИЗМЕНИТЬ ВИДИМОСТЬ");
    }
  }

  async function regenerateSelectedModuleQuizzes() {
    if (!selectedAdminModuleId) return;
    if (!window.confirm("Запустить реген тестов для выбранного модуля?")) return;
    try {
      setError(null);
      const res = await apiFetch<{ job_id?: string }>(
        `/admin/modules/${encodeURIComponent(selectedAdminModuleId)}/regenerate-quizzes`,
        { method: "POST" }
      );
      if (res?.job_id) {
        setSelectedJobId(String(res.job_id));
        goTab("import");
        setJobPanelOpen(true);
      }
      window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "РЕГЕН ЗАПУЩЕН", description: "" } }));
      void loadRegenHistory(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "НЕ УДАЛОСЬ ЗАПУСТИТЬ РЕГЕН");
    }
  }

  async function regenerateSubmoduleQuiz(submoduleId: string) {
    const sid = String(submoduleId || "").trim();
    if (!sid) return;
    if (!window.confirm("Запустить реген теста для выбранного урока?")) return;
    try {
      setError(null);
      const res = await apiFetch<{ job_id: string }>(
        `/admin/submodules/${encodeURIComponent(sid)}/regenerate-quiz`,
        { method: "POST" }
      );
      if (res?.job_id) {
        setSelectedJobId(String(res.job_id));
        goTab("import");
        setJobPanelOpen(true);
      }
      window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "РЕГЕН ЗАПУЩЕН", description: "" } }));
      void loadRegenHistory(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "НЕ УДАЛОСЬ ЗАПУСТИТЬ РЕГЕН");
    }
  }

  async function deleteSelectedModule() {
    if (!selectedAdminModuleId) return;
    const title = String(selectedAdminModule?.title || "").trim();
    if (!window.confirm(`Удалить модуль${title ? `\n\n${title}` : ""}?\n\nДействие необратимо.`)) return;
    const deletingId = String(selectedAdminModuleId);
    const prevModules = adminModules;
    const prevSelectedModuleId = selectedAdminModuleId;
    const prevSelectedSubmoduleId = selectedSubmoduleId;
    const prevSelectedQuizId = selectedQuizId;
    try {
      setError(null);
      setAdminModules((xs: AdminModuleItem[]) => (Array.isArray(xs) ? xs.filter((m) => String((m as any)?.id || "") !== deletingId) : xs));
      // Immediate UI feedback: clear selection right away so the deleted module disappears instantly.
      setSelectedAdminModuleId("");
      setSelectedSubmoduleId("");
      setSelectedQuizId("");
      await apiFetch(`/admin/modules/${encodeURIComponent(selectedAdminModuleId)}`, { method: "DELETE" });
      window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "МОДУЛЬ УДАЛЁН", description: "" } }));
      await loadAdminModulesForce();
    } catch (e) {
      setAdminModules(prevModules);
      setSelectedAdminModuleId(prevSelectedModuleId);
      setSelectedSubmoduleId(prevSelectedSubmoduleId);
      setSelectedQuizId(prevSelectedQuizId);
      setError(e instanceof Error ? e.message : "НЕ УДАЛОСЬ УДАЛИТЬ МОДУЛЬ");
    }
  }

  async function reloadModules() {
    try {
      const ms = await apiFetch<any[]>(`/modules`);
      const mapped = (ms || []).map((m) => ({ id: String(m.id), title: String(m.title) }));
      setModules(mapped);
      if (mapped.length && !moduleId) setModuleId(mapped[0].id);
    } catch { /* ignore */ }
  }

  async function createQuestionAdmin(quizId: string) {
    if (!quizId) return;
    try {
      setNewQuestionBusy(true);
      setError(null);
      const res = await apiFetch<{ id?: string }>(`/admin/quizzes/${encodeURIComponent(quizId)}/questions`, { method: "POST" });
      if (res?.id) {
        window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "ВОПРОС СОЗДАН", description: "" } }));
        await loadQuestionsForQuiz(quizId);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "НЕ УДАЛОСЬ СОЗДАТЬ ВОПРОС");
    } finally {
      setNewQuestionBusy(false);
    }
  }

  async function deleteQuestionAdmin(id: string) {
    if (!id) return;
    if (!window.confirm("Удалить вопрос?")) return;
    try {
      setError(null);
      await apiFetch(`/admin/questions/${encodeURIComponent(id)}`, { method: "DELETE" });
      window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "ВОПРОС УДАЛЁН", description: "" } }));
      if (selectedQuizId) await loadQuestionsForQuiz(selectedQuizId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "НЕ УДАЛОСЬ УДАЛИТЬ ВОПРОС");
    }
  }

  async function saveQuestionDraft(id: string) {
    const draft = questionDraftsById[id];
    if (!draft) return;
    try {
      setQuestionSavingId(id);
      await apiFetch(`/admin/questions/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(draft) });
      setQuestionDraftsById((prev: Record<string, any>) => { const n = { ...prev }; delete n[id]; return n; });
      await loadQuestionsForQuiz(selectedQuizId);
    } finally {
      setQuestionSavingId("");
    }
  }

  function getDraftValue(q: any, key: string) {
    return questionDraftsById[q.id]?.[key] ?? q[key];
  }

  function isQuestionDirty(q: any) {
    return !!questionDraftsById[q.id];
  }

  async function saveImportState() {
    // dummy function to prevent errors
  }

  // --- Effects ---
  useEffect(() => {
    selectedJobIdRef.current = String(selectedJobId || "");
  }, [selectedJobId]);

  useEffect(() => {
    jobPanelOpenRef.current = Boolean(jobPanelOpen);
  }, [jobPanelOpen]);

  useEffect(() => {
    if (authLoading) return;
    if (!user) return;

    let es: EventSource | null = null;
    let stopped = false;
    let reconnectTimer: number | null = null;
    let openedOnce = false;

    let backoffMs = 1000;
    const backoffMaxMs = 30_000;

    const isPageActive = () => {
      try {
        return document.visibilityState === "visible";
      } catch {
        return true;
      }
    };

    const isOnline = () => {
      try {
        return navigator.onLine !== false;
      } catch {
        return true;
      }
    };

    const clearReconnect = () => {
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const tryRefreshSession = async (): Promise<boolean> => {
      try {
        const res = await fetch("/api/auth/refresh", {
          method: "POST",
          cache: "no-store",
          credentials: "include",
        });
        return !!res.ok;
      } catch {
        return false;
      }
    };

    const scheduleReconnect = (reason: string) => {
      if (stopped) return;
      clearReconnect();
      if (!isOnline()) return;
      // If the tab is hidden, don't burn reconnect attempts.
      if (!isPageActive()) return;

      const jitter = Math.floor(Math.random() * 250);
      const delay = Math.min(backoffMaxMs, Math.max(250, backoffMs + jitter));
      backoffMs = Math.min(backoffMaxMs, Math.floor(backoffMs * 1.7));

      reconnectTimer = window.setTimeout(() => {
        if (stopped) return;
        open("reconnect:" + reason);
      }, delay);
    };

    const closeSse = (why: string) => {
      try {
        jobsLog("sse.close", { why });
      } catch {
        // ignore
      }
      try {
        es?.close();
      } catch {
        // ignore
      }
      es = null;
      setJobsSseConnected(false);
    };

    const open = (reason: string) => {
      if (stopped) return;
      clearReconnect();

      if (!isOnline()) {
        setJobsSseConnected(false);
        scheduleReconnect("offline");
        return;
      }

      if (!isPageActive()) {
        setJobsSseConnected(false);
        scheduleReconnect("hidden");
        return;
      }

      // Always close previous instance before opening a new one.
      if (es) closeSse("reopen");

      try {
        es = new EventSource("/api/backend/admin/jobs/events");
      } catch {
        es = null;
        setJobsSseConnected(false);
        scheduleReconnect("ctor_fail");
        return;
      }

      openedOnce = true;
      setJobsSseConnected(false);

      es.addEventListener("open", () => {
        jobsSseLastOkAtRef.current = Date.now();
        jobsSseLastRevRef.current = jobsSseLastRevRef.current || 0;
        backoffMs = 1000;
        setJobsSseConnected(true);
        jobsLog("sse.open", { reason });
      });

      es.addEventListener("error", () => {
        closeSse("error");
        // Best-effort: SSE cannot auto-refresh tokens like apiFetch does.
        // Try to refresh the session using refresh cookie, then reconnect with backoff.
        void tryRefreshSession().finally(() => scheduleReconnect("error"));
      });

      es.addEventListener("jobs", (ev: MessageEvent) => {
        jobsSseLastOkAtRef.current = Date.now();
        setJobsSseConnected(true);

        try {
          const payload = JSON.parse(String((ev as any)?.data || "{}")) as any;

          // Ignore out-of-order events to prevent UI regressions.
          const rev = Number(payload?.rev || 0);
          const lastRev = Number(jobsSseLastRevRef.current || 0);
          if (rev && rev <= lastRev) {
            jobsLog("sse.ignored", { rev, lastRev });
            return;
          }
          if (rev) jobsSseLastRevRef.current = rev;

          jobsLog("sse.jobs", {
            rev,
            ts: String(payload?.ts || ""),
            import_queue: Array.isArray(payload?.import?.queue) ? payload.import.queue.length : 0,
            import_has_current: Boolean(payload?.import?.current),
            import_history: Array.isArray(payload?.import?.history) ? payload.import.history.length : 0,
            regen_queue: Array.isArray(payload?.regen?.queue) ? payload.regen.queue.length : 0,
            regen_has_current: Boolean(payload?.regen?.current),
            regen_history: Array.isArray(payload?.regen?.history) ? payload.regen.history.length : 0,
          });

          // Apply canonical lane payload atomically.
          applyJobsModel(payload, "sse");
        } catch {
          // ignore
        }
      });
    };

    const onVisibility = () => {
      if (stopped) return;
      if (!isPageActive()) {
        // Close to reduce server load; we'll reconnect on visible.
        if (es) closeSse("hidden");
        return;
      }
      // When coming back, reconnect if needed.
      if (!es) open("visible");
    };

    const onOnline = () => {
      if (stopped) return;
      if (!es) open("online");
    };

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("online", onOnline);

    open("mount");

    return () => {
      stopped = true;
      clearReconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("online", onOnline);
      closeSse("unmount");
    };
  }, [authLoading, user]);

  useEffect(() => {
    if (authLoading) return;
    if (!user) return;

    let es: EventSource | null = null;
    let stopped = false;
    let backoffMs = 800;
    const backoffMaxMs = 15_000;
    let reconnectTimer: number | null = null;
    let lastRev = 0;

    const clearReconnect = () => {
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    };

    const scheduleReconnect = (why: string) => {
      if (stopped) return;
      clearReconnect();
      const jitter = Math.floor(Math.random() * 250);
      const delay = Math.min(backoffMaxMs, Math.max(250, backoffMs + jitter));
      backoffMs = Math.min(backoffMaxMs, Math.floor(backoffMs * 1.6));
      reconnectTimer = window.setTimeout(() => open("reconnect:" + why), delay);
    };

    const close = (why: string) => {
      try {
        es?.close();
      } catch {
        // ignore
      }
      es = null;
    };

    const open = (why: string) => {
      if (stopped) return;
      clearReconnect();
      close("reopen");
      try {
        es = new EventSource("/api/backend/modules/events");
      } catch {
        es = null;
        scheduleReconnect("ctor_fail");
        return;
      }

      es.addEventListener("error", () => {
        close("error");
        scheduleReconnect("error");
      });

      es.addEventListener("modules", (ev: MessageEvent) => {
        try {
          const payload = JSON.parse(String((ev as any)?.data || "{}")) as any;
          const rev = Number(payload?.rev || 0);
          if (rev && rev <= lastRev) return;
          if (rev) lastRev = rev;
        } catch {
          // ignore
        }
        void loadAdminModulesForce();
      });
    };

    open("mount");
    return () => {
      stopped = true;
      clearReconnect();
      close("unmount");
    };
  }, [authLoading, user]);

  useEffect(() => {
    if (authLoading) return;
    if (!user) return;

    let stopped = false;

    const shouldPollJobs = (): boolean => {
      // Only poll jobs when the UI actually needs them.
      // - modules: to keep regen queue markers authoritative
      // - import: to keep import queue + job panel consistent
      const needs = tab === "modules" || tab === "import";
      if (!needs) return false;

      const lastOk = Number(jobsSseLastOkAtRef.current || 0);
      const connected = Boolean(jobsSseConnected);
      const stale = !lastOk || Date.now() - lastOk > 20_000;
      // If SSE is connected and fresh, polling is unnecessary.
      if (connected && !stale) return false;
      return true;
    };

    const pollOnce = async (reason: string) => {
      if (stopped) return;
      if (!shouldPollJobs()) return;
      if (jobsPollInFlightRef.current) return;
      jobsPollInFlightRef.current = true;
      try {
        await loadJobsModel(true);
      } catch {
        // ignore
      } finally {
        jobsPollInFlightRef.current = false;
      }
    };

    // Fast first poll so UI heals quickly after reload.
    void pollOnce("mount");

    const id = window.setInterval(() => {
      void pollOnce("interval");
    }, 10_000);

    return () => {
      stopped = true;
      window.clearInterval(id);
    };
  }, [authLoading, user, jobsSseConnected, tab]);

  useEffect(() => {
    if (authLoading) return;
    if (!user) return;
    const id = String(selectedJobId || "").trim();
    if (!id) return;
    if (!jobPanelOpen) return;
    void hydrateJobPanel(id, "selected_change");
  }, [authLoading, user, selectedJobId, jobPanelOpen]);

  useEffect(() => {
    if (authLoading) return;
    if (!user) return;
    if (!jobPanelOpen) return;

    let stopped = false;
    const tick = async () => {
      if (stopped) return;
      const id = String(selectedJobIdRef.current || "").trim();
      if (!id) return;
      // Refresh only while the job is active; terminal jobs don't need constant polling.
      if (!hasActiveCurrentJob()) return;
      await hydrateJobPanel(id, "panel_watchdog");
    };

    void tick();
    const t = window.setInterval(() => {
      void tick();
    }, 2500);
    return () => {
      stopped = true;
      window.clearInterval(t);
    };
  }, [authLoading, user, jobPanelOpen]);

  useEffect(() => {
    if (didInitFromQueryRef.current) return;
    didInitFromQueryRef.current = true;

    const st = loadAdminUiState();
    const q = readAdminQuery();

    const mid = q.mid || String(st?.selectedAdminModuleId || "").trim() || "";
    const sid = q.sid || String(st?.selectedSubmoduleId || "").trim() || "";
    const qid = q.qid || String(st?.selectedQuizId || "").trim() || "";
    const uid = String(st?.selectedUserId || "").trim() || "";
    const uq = String(st?.userQuery || "").trim() || "";
    const iqv = String(st?.importQueueView || "").trim() as any;
    const jpOpen = Boolean(st?.jobPanelOpen);
    const sjid = String(st?.selectedJobId || "").trim() || "";

    if (mid) setSelectedAdminModuleId(mid);
    if (sid) setSelectedSubmoduleId(sid);
    if (qid) setSelectedQuizId(qid);
    if (uid) setSelectedUserId(uid);
    if (uq) setUserQuery(uq);
    if (iqv === "active" || iqv === "history") setImportQueueView(iqv);
    if (sjid) setSelectedJobId(sjid);
    if (jpOpen) setJobPanelOpen(true);
  }, []);

  useEffect(() => {
    if (!didInitFromQueryRef.current) return;
    saveAdminUiState({
      selectedAdminModuleId: String(selectedAdminModuleId || "").trim(),
      selectedSubmoduleId: String(selectedSubmoduleId || "").trim(),
      selectedQuizId: String(selectedQuizId || "").trim(),
      selectedUserId: String(selectedUserId || "").trim(),
      userQuery: String(userQuery || "").trim(),
      importQueueView: String(importQueueView || "").trim(),
      jobPanelOpen: Boolean(jobPanelOpen),
      selectedJobId: String(selectedJobId || "").trim(),
    });
  }, [selectedAdminModuleId, selectedSubmoduleId, selectedQuizId, selectedUserId, userQuery, importQueueView, jobPanelOpen, selectedJobId]);

  useEffect(() => {
    const t = tabFromPath(pathname);
    if (t !== tab) setTab(t);
  }, [pathname]);

  useEffect(() => {
    if (tab === "users") void loadUsers();
    if (tab === "diagnostics") { void loadSystemStatus(); void Promise.all([loadRuntimeLlmSettings(), loadRuntimeS3Settings()]); }
    if (tab === "modules") void loadAdminModules();
    if (tab === "analytics") void Promise.all([loadUsers(), loadAdminModules()]);
    if (tab === "import") {
      void loadJobsModel(true);
    }
  }, [tab]);

  useEffect(() => {
    if (selectedAdminModuleId) void loadSelectedAdminModule();
  }, [selectedAdminModuleId]);

  useEffect(() => {
    if (selectedUserId) void loadUserDetail(selectedUserId);
  }, [selectedUserId]);

  useEffect(() => {
    const qid = String(selectedQuizId || "").trim();
    if (!qid) return;

    try {
      const cached = questionsByQuizId[qid];
      if (Array.isArray(cached)) return;
    } catch {
      // ignore
    }

    if (questionsLoadingQuizId) return;
    void loadQuestionsForQuiz(qid);
  }, [selectedQuizId]);

  // --- Render logic ---
  const selectedAdminModule = useMemo(() => adminModules.find((m: AdminModuleItem) => String(m.id) === String(selectedAdminModuleId)) || null, [adminModules, selectedAdminModuleId]);
  const selectedAdminModuleQuality = useMemo(() => (selectedAdminModule as any)?.question_quality || { total_current: 0, needs_regen_current: 0, fallback_current: 0, ai_current: 0, heur_current: 0 }, [selectedAdminModule]);
  const selectedQuizQuestions = useMemo(() => questionsByQuizId[selectedQuizId] || [], [questionsByQuizId, selectedQuizId]);
  const activeModuleRegenByModuleId = useMemo(() => {
    const out: Record<string, any> = {};
    regenHistory.forEach((it: any) => { if (it.module_id && !it.submodule_id && it.status !== "finished") out[it.module_id] = it; });
    return out;
  }, [regenHistory]);
  const activeSubmoduleRegenBySubmoduleId = useMemo(() => {
    const out: Record<string, any> = {};
    regenHistory.forEach((it: any) => { if (it.submodule_id && it.status !== "finished") out[it.submodule_id] = it; });
    return out;
  }, [regenHistory]);

  const analytics = useMemo(() => {
    const registered = Array.isArray(users) ? users.length : 0;
    const now = Date.now();
    const onlineWindowMs = 10 * 60 * 1000;
    const online = (Array.isArray(users) ? users : []).filter((u: any) => {
      const ts = String(u?.last_activity_at || "").trim();
      if (!ts) return false;
      const t = Date.parse(ts);
      if (!t || !Number.isFinite(t)) return false;
      return now - t <= onlineWindowMs;
    }).length;

    const byCurrentModule: Record<string, { id: string; title: string; count: number }> = {};
    for (const u of Array.isArray(users) ? users : []) {
      const cur = (u as any)?.progress_summary?.current;
      const mid = String(cur?.module_id || "").trim();
      if (!mid) continue;
      const title = String(cur?.title || "").trim();
      if (!byCurrentModule[mid]) byCurrentModule[mid] = { id: mid, title, count: 0 };
      byCurrentModule[mid].count += 1;
      if (title && !byCurrentModule[mid].title) byCurrentModule[mid].title = title;
    }

    const popularCurrent = Object.values(byCurrentModule)
      .sort((a, b) => (b.count - a.count) || String(a.title).localeCompare(String(b.title)))
      .slice(0, 5);

    const mostPopular = popularCurrent.length ? popularCurrent[0] : null;

    let mostProblematic: { id: string; title: string; needs: number } | null = null;
    for (const m of Array.isArray(adminModules) ? adminModules : []) {
      const q = (m as any)?.question_quality;
      const needs = Number(q?.needs_regen_current || 0);
      if (!mostProblematic || needs > mostProblematic.needs) {
        mostProblematic = { id: String((m as any)?.id || ""), title: String((m as any)?.title || ""), needs };
      }
    }

    return {
      registered,
      online,
      mostPopular,
      mostProblematic,
      popularCurrent,
    };
  }, [users, adminModules]);

  const switchTabGuarded = (next: TabKey) => {
    if (next === tab) return;
    goTab(next);
  };

  const tabLabelRu: Record<TabKey, string> = {
    modules: "МОДУЛИ",
    import: "ИМПОРТ",
    analytics: "АНАЛИТИКА",
    users: "ПОЛЬЗОВАТЕЛИ",
    diagnostics: "ДИАГНОСТИКА",
  };

  const shareUrl = useMemo(() => {
    try {
      const base = window.location.origin;
      const sp = new URLSearchParams();

      if (tab === "modules") {
        const mid = String(selectedAdminModuleId || "").trim();
        const sid = String(selectedSubmoduleId || "").trim();
        const qid = String(selectedQuizId || "").trim();
        if (mid) sp.set("mid", mid);
        if (sid) sp.set("sid", sid);
        if (qid) sp.set("qid", qid);
      }

      const qs = sp.toString();
      return qs ? `${base}${pathForTab(tab)}?${qs}` : `${base}${pathForTab(tab)}`;
    } catch {
      return "";
    }
  }, [tab, selectedAdminModuleId, selectedSubmoduleId, selectedQuizId]);

  if (authLoading) return <div className="flex min-h-screen items-center justify-center"><div className="h-12 w-12 rounded-full border-2 border-[#fe9900]/30 border-t-[#fe9900] animate-spin" /></div>;

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-7xl px-4 py-10">
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Каркас Тайги</div>
            <h1 className="mt-2 text-3xl font-black tracking-tighter text-zinc-950 uppercase">Админ-панель</h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="h-10 rounded-xl border border-zinc-200 bg-white px-4 text-[10px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
              onClick={() => void copy(shareUrl)}
              disabled={!shareUrl}
              title="Скопировать ссылку на текущий раздел"
            >
              ССЫЛКА
            </button>
            <div className="flex items-center gap-2 rounded-2xl border border-zinc-200 bg-white p-2">
              {(["modules", "import", "analytics", "users", "diagnostics"] as TabKey[]).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => switchTabGuarded(t)}
                  className={
                    "h-10 rounded-xl px-4 text-[10px] font-black uppercase tracking-widest transition " +
                    (tab === t
                      ? "bg-[#fe9900]/15 text-zinc-950 border border-[#fe9900]/25"
                      : "text-zinc-600 hover:text-zinc-950 hover:bg-zinc-50 border border-transparent")
                  }
                >
                  {tabLabelRu[t] || t.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
        </div>

        {error && (
          <div className="mt-6 rounded-[24px] border border-rose-200 bg-rose-50 p-5 text-sm font-bold text-rose-800 flex justify-between items-center">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="text-rose-400 hover:text-rose-600">✕</button>
          </div>
        )}

        <div className="mt-8">
          {tab === "modules" && (
            <ModulesTab
              adminModules={adminModules}
              adminModulesLoading={adminModulesLoading}
              loadAdminModules={loadAdminModules}
              reconcileModulesStorage={reconcileModulesStorage}
              selectedAdminModuleId={selectedAdminModuleId}
              setSelectedAdminModuleId={setSelectedAdminModuleId}
              selectedAdminModule={selectedAdminModule}
              setSelectedModuleVisibility={setSelectedModuleVisibility}
              activeModuleRegenByModuleId={activeModuleRegenByModuleId}
              activeSubmoduleRegenBySubmoduleId={activeSubmoduleRegenBySubmoduleId}
              regenerateSelectedModuleQuizzes={regenerateSelectedModuleQuizzes}
              deleteSelectedModule={deleteSelectedModule}
              selectedAdminModuleSubsLoading={selectedAdminModuleSubsLoading}
              selectedAdminModuleSubs={selectedAdminModuleSubs}
              selectedAdminModuleSubsQuality={subQualityByModuleId[selectedAdminModuleId] || []}
              selectedAdminModuleSubsQualityLoading={subQualityLoadingByModuleId[selectedAdminModuleId] || false}
              regenerateSubmoduleQuiz={regenerateSubmoduleQuiz}
              purgeOrphanStorage={purgeOrphanStorage}
              isStorageScanning={isStorageScanning}
              storageOrphansCount={storageOrphansCount}
              selectedSubmoduleId={selectedSubmoduleId}
              setSelectedSubmoduleId={setSelectedSubmoduleId}
              setSelectedQuizId={setSelectedQuizId}
              selectedQuizId={selectedQuizId}
              newQuestionBusy={newQuestionBusy}
              createQuestionAdmin={createQuestionAdmin}
              questionsLoadingQuizId={questionsLoadingQuizId}
              loadQuestionsForQuiz={loadQuestionsForQuiz}
              selectedQuizQuestions={selectedQuizQuestions}
              isQuestionDirty={isQuestionDirty}
              questionSavingId={questionSavingId}
              saveQuestionDraft={saveQuestionDraft}
              copy={copy}
              deleteQuestionAdmin={deleteQuestionAdmin}
              getDraftValue={getDraftValue}
              setQuestionDraftsById={setQuestionDraftsById}
            />
          )}
          {tab === "users" && (
            <UsersTab
              currentUserId={String((user as any)?.id || "")}
              newUserBusy={newUserBusy}
              createUser={createUser}
              newUserName={newUserName}
              setNewUserName={setNewUserName}
              newUserEmail={newUserEmail}
              setNewUserEmail={setNewUserEmail}
              newUserRole={newUserRole}
              setNewUserRole={setNewUserRole}
              usersLoading={usersLoading}
              loadUsers={loadUsers}
              newUserTempPassword={newUserTempPassword}
              copy={copy}
              users={users}
              userQuery={userQuery}
              setUserQuery={setUserQuery}
              selectedUserId={selectedUserId}
              setSelectedUserId={setSelectedUserId}
              userDetail={userDetail}
              userDetailLoading={userDetailLoading}
              updateSelectedUser={updateSelectedUser}
              resetBusy={resetBusy}
              resetPassword={resetPassword}
              deleteUserBusy={deleteUserBusy}
              deleteSelectedUser={deleteSelectedUser}
              userHistoryLoading={userHistoryLoading}
              userHistoryDetailed={userHistoryDetailed}
              resetTempPassword={resetTempPassword}
              tempPasswordModalOpen={tempPasswordModalOpen}
              setTempPasswordModalOpen={(open) => {
                if (!open) closeTempPasswordModal();
                else setTempPasswordModalOpen(true);
              }}
            />
          )}
          {tab === "analytics" && (
            <div className="grid gap-6 lg:grid-cols-12 items-start">
              <div className="lg:col-span-8 relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-10 shadow-2xl shadow-zinc-950/10">
                <div className="flex items-start justify-between gap-6">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900] mb-2">Сводка</div>
                    <div className="text-2xl font-black tracking-tighter text-zinc-950 uppercase leading-none">Аналитика</div>
                    <div className="mt-3 text-[10px] font-black uppercase tracking-widest text-zinc-500">без новых эндпоинтов</div>
                  </div>
                  <Button
                    variant="ghost"
                    className="h-11 rounded-xl font-black uppercase tracking-widest text-[9px]"
                    disabled={usersLoading || adminModulesLoading}
                    onClick={() => void Promise.all([loadUsersForce(), loadAdminModulesForce()])}
                  >
                    {usersLoading || adminModulesLoading ? "ОБНОВЛЕНИЕ..." : "ОБНОВИТЬ"}
                  </Button>
                </div>

                <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Пользователей</div>
                    <div className="mt-2 text-3xl font-black tabular-nums text-zinc-950">{analytics.registered}</div>
                  </div>
                  <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Онлайн (≈10 мин)</div>
                    <div className="mt-2 text-3xl font-black tabular-nums text-zinc-950">{analytics.online}</div>
                  </div>
                  <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Популярный модуль</div>
                    <div className="mt-2 text-[11px] font-black uppercase tracking-widest text-zinc-950 truncate">
                      {analytics.mostPopular ? analytics.mostPopular.title || analytics.mostPopular.id : "—"}
                    </div>
                    <div className="mt-2 text-[9px] font-black uppercase tracking-widest text-zinc-600">
                      {analytics.mostPopular ? `в работе: ${analytics.mostPopular.count}` : ""}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Проблемный модуль</div>
                    <div className="mt-2 text-[11px] font-black uppercase tracking-widest text-zinc-950 truncate">
                      {analytics.mostProblematic ? analytics.mostProblematic.title || analytics.mostProblematic.id : "—"}
                    </div>
                    <div className="mt-2 text-[9px] font-black uppercase tracking-widest text-zinc-600">
                      {analytics.mostProblematic ? `needs regen: ${analytics.mostProblematic.needs}` : ""}
                    </div>
                  </div>
                </div>

                <div className="mt-8 rounded-2xl border border-zinc-200 bg-white p-6">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Топ модулей</div>
                      <div className="mt-2 text-lg font-black uppercase text-zinc-950">Сейчас в работе</div>
                    </div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-600">{analytics.popularCurrent.length}</div>
                  </div>

                  <div className="mt-5 space-y-2">
                    {analytics.popularCurrent.length ? (
                      analytics.popularCurrent.map((x: { id: string; title?: string; count: number }) => (
                        <div key={x.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 rounded-xl border border-zinc-200 bg-zinc-50/40 px-4 py-3">
                          <div className="min-w-0">
                            <div className="truncate text-[11px] font-black uppercase tracking-widest text-zinc-950">{x.title || x.id}</div>
                            <div className="mt-1 text-[9px] font-black uppercase tracking-widest text-zinc-500">ID: {String(x.id).slice(0, 8)}</div>
                          </div>
                          <div className="shrink-0 rounded-full border border-[#fe9900]/25 bg-[#fe9900]/10 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-900 tabular-nums">
                            {x.count}
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="py-10 text-center text-[10px] font-black uppercase tracking-widest text-zinc-500">Нет данных</div>
                    )}
                  </div>
                </div>
              </div>

              <div className="lg:col-span-4 space-y-6">
                <div className="relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-8 shadow-2xl shadow-zinc-950/10">
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Примечание</div>
                  <div className="mt-2 text-sm font-bold text-zinc-600">
                    Онлайн считается по последней активности пользователя (поле last_activity_at) за ~10 минут.
                  </div>
                </div>
              </div>
            </div>
          )}
          {tab === "diagnostics" && (
            <DiagnosticsTab
              sys={sys}
              sysLoading={sysLoading}
              loadSystemStatus={loadSystemStatus}
              openrouterEnabledDraft={openrouterEnabledDraft}
              setOpenrouterEnabledDraft={setOpenrouterEnabledDraft}
              openrouterBaseUrlDraft={openrouterBaseUrlDraft}
              setOpenrouterBaseUrlDraft={setOpenrouterBaseUrlDraft}
              openrouterModelDraft={openrouterModelDraft}
              setOpenrouterModelDraft={setOpenrouterModelDraft}
              openrouterApiKeyDraft={openrouterApiKeyDraft}
              setOpenrouterApiKeyDraft={setOpenrouterApiKeyDraft}
              openrouterApiKeyMasked={openrouterApiKeyMasked}
              openrouterHttpRefererDraft={openrouterHttpRefererDraft}
              setOpenrouterHttpRefererDraft={setOpenrouterHttpRefererDraft}
              openrouterAppTitleDraft={openrouterAppTitleDraft}
              setOpenrouterAppTitleDraft={setOpenrouterAppTitleDraft}
              llmEffective={llmEffective}
              diagSaving={diagSaving}
              saveRuntimeLlmSettings={saveRuntimeLlmSettings}
              loadRuntimeLlmSettings={loadRuntimeLlmSettings}
              resetRuntimeLlmSettings={resetRuntimeLlmSettings}

              s3Draft={s3Draft}
              setS3Draft={setS3Draft}
              saveRuntimeS3Settings={saveRuntimeS3Settings}
              loadRuntimeS3Settings={loadRuntimeS3Settings}
              resetRuntimeS3Settings={resetRuntimeS3Settings}
              brokenModulesBusy={brokenModulesBusy}
              brokenModules={brokenModules}
              brokenModulesCount={brokenModulesCount}
              scanBrokenModules={scanBrokenModules}
              purgeBrokenModules={purgeBrokenModules}
              modulesStorageScanBusy={modulesStorageScanBusy}
              modulesStorageScan={modulesStorageScan}
              scanModulesStorage={scanModulesStorage}
            />
          )}
          {tab === "import" && (
            <ImportTab
              importFiles={importFiles}
              importInputRef={importInputRef}
              setImportFiles={setImportFiles}
              importStageLabel={clientImportStage}
              uploadHistory={uploadHistory}
              s3UploadProgress={s3UploadProgress}
              importPendingCount={importPendingCount}
              importPendingNames={importPendingNames}
              importEnqueueProgress={importEnqueueProgress}
              importBatch={importBatch}
              importBusy={importBusy}
              startImport={startImport}
              importQueue={importQueue}
              importQueueLoading={importQueueLoading}
              importQueueWorkers={importQueueWorkers}
              loadImportQueue={loadImportQueue}
              storageUploads={storageUploads}
              storageUploadsLoading={storageUploadsLoading}
              storageUploadsPrefix={storageUploadsPrefix}
              storageUploadsDebug={storageUploadsDebug}
              loadStorageUploads={loadStorageUploads}
              enqueueImportFromS3={enqueueImportFromS3}
              adminModules={adminModules}
              setImportQueueView={setImportQueueView}
              setImportQueueModalOpen={setImportQueueModalOpen}
              importQueueModalOpen={importQueueModalOpen}
              importQueueView={importQueueView}
              importQueueHistory={importQueueHistory}
              setSelectedJobId={setSelectedJobId}
              setJobPanelOpen={setJobPanelOpen}
              cancelImportJob={cancelImportJob}
              cancelRegenJob={cancelRegenJob}
              retryImportJob={retryImportJob}
              openModuleFromImport={openModuleFromImport}
              regenQueue={regenQueue}
              regenHistoryLoading={regenHistoryLoading}
              loadRegenHistory={loadRegenHistory}
              regenQueueWorkers={regenQueueWorkers}
              setRegenQueueModalOpen={setRegenQueueModalOpen}
              regenQueueModalOpen={regenQueueModalOpen}
              regenHistory={regenHistory}
              clearAdminJobHistory={clearAdminJobHistory}
              jobPanelOpen={jobPanelOpen}
              selectedJobId={selectedJobId}
              jobStatus={jobStatus}
              jobStage={jobStage}
              jobStageAt={jobStageAt}
              jobStageStartedAt={jobStageStartedAt}
              jobStageDurations={jobStageDurations}
              jobStartedAt={jobStartedAt}
              importJobStageLabel={jobStage}
              copy={copy}
              cancelCurrentJob={cancelCurrentJob}
              cancelBusy={cancelBusy}
              jobKind={jobKind}
              jobModuleTitle={jobModuleTitle}
              jobModuleId={jobModuleId}
              jobDetail={jobDetail}
              jobError={jobError}
              jobErrorCode={jobErrorCode}
              jobErrorHint={jobErrorHint}
              clientImportStage={clientImportStage}
              clientImportFileName={clientImportFileName}
              selectedAdminModule={selectedAdminModule}
              selectedAdminModuleQuality={selectedAdminModuleQuality}
              jobResult={jobResult}
              cancelActiveUpload={cancelActiveUpload}
            />
          )}
        </div>
      </div>
    </AppShell>
  );
}
