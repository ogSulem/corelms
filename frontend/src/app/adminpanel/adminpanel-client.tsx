"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/hooks/use-auth";

type Module = { id: string; title: string };

import { DiagnosticsTab } from "./_components/DiagnosticsTab";
import { UsersTab } from "./_components/UsersTab";
import { ModulesTab } from "./_components/ModulesTab";
import { ImportTab } from "./_components/ImportTab";

export type RegenJobItem = {
  job_id: string;
  module_id?: string;
  module_title?: string;
  target_questions?: number;
  created_at?: string;
  status?: string;
  stage?: string;
  detail?: string;
  error_code?: string;
  error_hint?: string;
  error_message?: string;
  error?: string | null;
};

export type ImportJobItem = {
  job_id: string;
  object_key?: string;
  title?: string;
  source_filename?: string;
  module_id?: string;
  module_title?: string;
  created_at?: string;
  status?: string;
  stage?: string;
  detail?: string;
  error_code?: string;
  error_hint?: string;
  error_message?: string;
  error?: string | null;
};

type Row = {
  user_id: string;
  name: string;
  role: string;
  read_count: number;
  passed_count: number;
  total_lessons: number;
  final_passed: boolean;
  completed: boolean;
  last_activity: string | null;
};

type Report = { module_id: string; module_title: string; rows: Row[] };

type QuestionQualityItem = {
  question_id: string;
  quiz_id: string;
  quiz_type: string;
  type: string;
  concept_tag: string | null;
  prompt: string;
  total: number;
  incorrect: number;
  failure_rate: number;
};

type StatusFilter = "all" | "completed" | "in_progress" | "not_started";
type SortKey = "name" | "progress" | "last_activity";
type TabKey = "modules" | "import" | "analytics" | "users" | "diagnostics";

function formatEventTypeRu(eventType: string): string {
  const k = String(eventType || "").trim().toLowerCase();
  if (!k) return "СОБЫТИЕ";
  const map: Record<string, string> = {
    user_login: "ВХОД",
    user_logout: "ВЫХОД",
    quiz_started: "ТЕСТ НАЧАТ",
    quiz_submitted: "ТЕСТ СДАН",
    quiz_passed: "ТЕСТ ПРОЙДЕН",
    quiz_failed: "ТЕСТ НЕ ПРОЙДЕН",
    module_started: "МОДУЛЬ НАЧАТ",
    module_completed: "МОДУЛЬ ЗАВЕРШЁН",
    lesson_opened: "УРОК ОТКРЫТ",
    lesson_completed: "УРОК ПРОЙДЕН",
    assignment_started: "НАЗНАЧЕНИЕ НАЧАТО",
    assignment_completed: "НАЗНАЧЕНИЕ ВЫПОЛНЕНО",
    password_changed: "ПАРОЛЬ ИЗМЕНЁН",
    admin_reset_password: "АДМИН СБРОСИЛ ПАРОЛЬ",
    admin_regenerate_module_quizzes: "РЕГЕН ТЕСТОВ",
    admin_import_module: "ИМПОРТ МОДУЛЯ",
  };
  if (map[k]) return map[k];
  return String(eventType || "").replace(/_/g, " ").toUpperCase();
}

export type AdminModuleItem = {
  id: string;
  title: string;
  is_active: boolean;
  final_quiz_id?: string | null;
  category?: string | null;
  difficulty?: number | null;
  question_quality?: {
    total_current: number;
    needs_regen_current: number;
    fallback_current: number;
    ai_current: number;
    heur_current: number;
  };
};

export type AdminSubmoduleItem = {
  id: string;
  module_id: string;
  title: string;
  order: number;
  quiz_id: string;
};

export type AdminSubmoduleQualityItem = {
  submodule_id: string;
  order: number;
  title: string;
  quiz_id: string | null;
  total: number;
  needs_regen: number;
  fallback: number;
  ai: number;
  heur: number;
  ok: boolean;
};

export type AdminQuestionItem = {
  id: string;
  quiz_id: string;
  type: string;
  difficulty: number;
  prompt: string;
  correct_answer: string;
  explanation?: string | null;
  concept_tag?: string | null;
  variant_group?: string | null;
};

export type UserItem = {
  id: string;
  name: string;
  role: string;
  position?: string | null;
  xp?: number;
  level?: number;
  streak?: number;
  last_activity_at?: string | null;
  created_at?: string | null;
  progress_summary?: {
    completed_count?: number;
    in_progress_count?: number;
    current?: { module_id: string; title: string; total: number; passed: number; percent: number } | null;
  };
};

export type UserModuleProgress = {
  module_id: string;
  title: string;
  total: number;
  passed: number;
  percent: number;
  completed: boolean;
};

export type UserHistoryItem = {
  id: string;
  event_type: string;
  created_at: string;
  meta: any;
};

export type UserHistoryDetailedItem = {
  id: string;
  created_at: string;
  kind: string;
  title: string;
  subtitle?: string | null;
  href?: string | null;
  event_type?: string | null;
  ref_id?: string | null;
  meta?: string | null;
  module_id?: string | null;
  module_title?: string | null;
  submodule_id?: string | null;
  submodule_title?: string | null;
  asset_id?: string | null;
  asset_name?: string | null;
};

export type UserDetail = {
  id: string;
  name: string;
  role: string;
  position: string | null;
  xp: number;
  level: number;
  streak: number;
  must_change_password: boolean;
  stats: {
    assignments_total: number;
    assignments_completed: number;
    attempts_total: number;
    attempts_passed: number;
    events_total: number;
  };
  modules_progress: {
    completed: UserModuleProgress[];
    in_progress: UserModuleProgress[];
  };
  history: UserHistoryItem[];
};

export default function AdminPanelClient() {
  const { user, loading: authLoading } = useAuth();

  const IMPORT_STATE_KEY = "corelms:admin_import_state";

  const importQueueSigRef = useRef<string>("");
  const importQueueHistorySigRef = useRef<string>("");
  const regenHistorySigRef = useRef<string>("");

  async function loadImportQueue(limit = 20, includeTerminal: boolean = false, silent: boolean = false) {
    try {
      if (!silent) setImportQueueLoading(true);
      const res = await apiFetch<{ items: any[]; history?: any[] }>(
        `/admin/import-jobs?limit=${encodeURIComponent(String(limit))}&include_terminal=${includeTerminal ? "true" : "false"}` as any
      );
      const items = Array.isArray(res?.items) ? res.items : [];
      const hist = Array.isArray((res as any)?.history) ? (res as any).history : [];
      const nextQueue = items.map((x: any) => ({
          job_id: String((x as any)?.job_id || (x as any)?.id || ""),
          object_key: String((x as any)?.object_key || ""),
          title: String((x as any)?.title || ""),
          source_filename: String((x as any)?.source_filename || ""),
          module_id: (x as any)?.module_id ? String((x as any).module_id) : undefined,
          module_title: (x as any)?.module_title ? String((x as any).module_title) : undefined,
          created_at: (x as any)?.created_at ? String((x as any).created_at) : undefined,
          status: (x as any)?.status ? String((x as any).status) : undefined,
          stage: (x as any)?.stage ? String((x as any).stage) : undefined,
          detail: (x as any)?.detail ? String((x as any).detail) : undefined,
          error_code: (x as any)?.error_code ? String((x as any).error_code) : undefined,
          error_hint: (x as any)?.error_hint ? String((x as any).error_hint) : undefined,
          error_message: (x as any)?.error_message ? String((x as any).error_message) : undefined,
          error: (x as any)?.error ? String((x as any).error) : null,
        }));
      const nextHist = hist.map((x: any) => ({
          job_id: String((x as any)?.job_id || (x as any)?.id || ""),
          object_key: String((x as any)?.object_key || ""),
          title: String((x as any)?.title || ""),
          source_filename: String((x as any)?.source_filename || ""),
          module_id: (x as any)?.module_id ? String((x as any).module_id) : undefined,
          module_title: (x as any)?.module_title ? String((x as any).module_title) : undefined,
          created_at: (x as any)?.created_at ? String((x as any).created_at) : undefined,
          status: (x as any)?.status ? String((x as any).status) : undefined,
          stage: (x as any)?.stage ? String((x as any).stage) : undefined,
          detail: (x as any)?.detail ? String((x as any).detail) : undefined,
          error_code: (x as any)?.error_code ? String((x as any).error_code) : undefined,
          error_hint: (x as any)?.error_hint ? String((x as any).error_hint) : undefined,
          error_message: (x as any)?.error_message ? String((x as any).error_message) : undefined,
          error: (x as any)?.error ? String((x as any).error) : null,
        }));

      const sig = JSON.stringify(nextQueue);
      if (sig !== importQueueSigRef.current) {
        importQueueSigRef.current = sig;
        setImportQueue(nextQueue);
      }
      const hsig = JSON.stringify(nextHist);
      if (hsig !== importQueueHistorySigRef.current) {
        importQueueHistorySigRef.current = hsig;
        setImportQueueHistory(nextHist);
      }
    } catch {
      setImportQueue([]);
      setImportQueueHistory([]);
    } finally {
      if (!silent) setImportQueueLoading(false);
    }
  }

  async function retryImportJob(jobId: string) {
    const id = String(jobId || "").trim();
    if (!id) return;
    try {
      await apiFetch<any>(`/admin/import-jobs/${encodeURIComponent(id)}/retry`, { method: "POST" } as any);
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: { title: "ПОВТОР ЗАПУЩЕН", description: `JOB: ${id}` },
        })
      );
      await loadImportQueue(50, true, false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ ПОВТОРИТЬ JOB");
    }
  }

  function openModuleFromImport(it: ImportJobItem) {
    const mid = String((it as any)?.module_id || "").trim();
    if (!mid) return;
    try {
      // In this admin UI, selecting a module is enough to open its details and submodules.
      setSelectedAdminModuleId(mid);
      setTab("modules");
      setImportQueueModalOpen(false);
    } catch {
      // ignore
    }
  }

  async function cancelImportJob(jobId: string) {
    const id = String(jobId || "").trim();
    if (!id) return;
    const ok = window.confirm(
      "Отменить импорт?\n\nОтмена доступна только пока задача в очереди. Если импорт уже в работе — отмена будет запрещена."
    );
    if (!ok) return;
    try {
      setCancelBusy(true);
      await apiFetch<any>(`/admin/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" } as any);
      if (String(selectedJobId || "").trim() === id) {
        setJobStage("canceled");
        setJobStatus("canceled");
      }
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: { title: "ИМПОРТ ОТМЕНЁН", description: `JOB: ${id}` },
        })
      );
      await Promise.all([loadImportQueue(50, true, false), loadAdminModules(), reloadModules()]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ ОТМЕНИТЬ ИМПОРТ");
    } finally {
      setCancelBusy(false);
    }
  }

  async function cancelRegenJob(jobId: string) {
    const id = String(jobId || "").trim();
    if (!id) return;
    const ok = window.confirm("Остановить генерацию тестов?\n\nЗадача будет немедленно отменена. Модуль останется скрыт до готовности.");
    if (!ok) return;
    try {
      setCancelBusy(true);
      await apiFetch<any>(`/admin/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" } as any);
      if (String(selectedJobId || "").trim() === id) {
        setJobStage("canceled");
        setJobStatus("canceled");
      }
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: { title: "РЕГЕН ОТМЕНЁН", description: `JOB: ${id}` },
        })
      );
      await Promise.all([loadRegenHistory(false), loadImportQueue(50, true, false), loadAdminModules(), reloadModules()]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ ОТМЕНИТЬ РЕГЕН");
    } finally {
      setCancelBusy(false);
    }
  }

  function saveImportState(partial?: any) {
    try {
      const cur = (() => {
        try {
          const raw = window.localStorage.getItem(IMPORT_STATE_KEY);
          return raw ? JSON.parse(raw) : {};
        } catch {
          return {};
        }
      })();
      const next = {
        ...cur,
        ...(partial || {}),
        selectedJobId,
        jobPanelOpen,
        importBatchJobIds: Array.from(new Set(importBatchJobIdsRef.current || [])).filter(Boolean),
        clientImportStage,
        clientImportFileName,
        ts: Date.now(),
      };
      window.localStorage.setItem(IMPORT_STATE_KEY, JSON.stringify(next));
    } catch {
      // ignore
    }
  }

  function clearImportState() {
    try {
      window.localStorage.removeItem(IMPORT_STATE_KEY);
    } catch {
      // ignore
    }
  }

  const [modules, setModules] = useState<Module[]>([]);
  const [moduleId, setModuleId] = useState<string>("");
  const [report, setReport] = useState<Report | null>(null);
  const [analyticsMode, setAnalyticsMode] = useState<"people" | "content">("people");
  const [quality, setQuality] = useState<QuestionQualityItem[]>([]);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [status, setStatus] = useState<StatusFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("progress");
  const [analyticsQuery, setAnalyticsQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [tab, setTab] = useState<TabKey>("modules");

  const [importFiles, setImportFiles] = useState<File[]>([]);
  const [importBusy, setImportBusy] = useState(false);
  const [importBatch, setImportBatch] = useState<{ total: number; done: number } | null>(null);
  const [importEnqueueProgress, setImportEnqueueProgress] = useState<{ total: number; done: number } | null>(null);
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

  const importBatchJobIdsRef = useRef<string[]>([]);
  const importCancelRequestedRef = useRef(false);
  const importUploadAbortRef = useRef<AbortController | null>(null);
  const importUploadObjectKeyRef = useRef<string>("");
  const importUploadFilenameRef = useRef<string>("");
  const importInputRef = useRef<HTMLInputElement | null>(null);

  const [clientImportStage, setClientImportStage] = useState<string>("");
  const [clientImportFileName, setClientImportFileName] = useState<string>("");

  const [s3UploadProgress, setS3UploadProgress] = useState<
    | {
        loaded: number;
        total: number;
        startedAtMs: number;
        lastAtMs: number;
        lastLoaded: number;
        speedBps: number;
        etaSeconds: number | null;
        percent: number;
      }
    | null
  >(null);

  const [regenHistory, setRegenHistory] = useState<any[]>([]);
  const [regenHistoryLoading, setRegenHistoryLoading] = useState(false);
  const [regenQueueModalOpen, setRegenQueueModalOpen] = useState(false);

  const [importQueue, setImportQueue] = useState<ImportJobItem[]>([]);
  const [importQueueLoading, setImportQueueLoading] = useState(false);
  const [importQueueModalOpen, setImportQueueModalOpen] = useState(false);
  const [importQueueHistory, setImportQueueHistory] = useState<ImportJobItem[]>([]);
  const [importQueueView, setImportQueueView] = useState<"active" | "history">("active");

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
  const [newQuestionBusy, setNewQuestionBusy] = useState(false);
  const [questionDraftsById, setQuestionDraftsById] = useState<Record<string, Partial<AdminQuestionItem>>>({});

  const FINAL_SUBMODULE_KEY = "__final__";

  const [needsRegenByModuleId, setNeedsRegenByModuleId] = useState<Record<string, number>>({});

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
  const [newUserPosition, setNewUserPosition] = useState("");
  const [newUserRole, setNewUserRole] = useState<"employee" | "admin">("employee");
  const [newUserBusy, setNewUserBusy] = useState(false);
  const [newUserTempPassword, setNewUserTempPassword] = useState<string>("");

  const [resetBusy, setResetBusy] = useState(false);
  const [resetTempPassword, setResetTempPassword] = useState<string>("");

  const [sys, setSys] = useState<any>(null);
  const [sysLoading, setSysLoading] = useState(false);
  const [llmOrderDraft, setLlmOrderDraft] = useState<string>("");
  const [ollamaEnabledDraft, setOllamaEnabledDraft] = useState<boolean>(false);
  const [ollamaBaseUrlDraft, setOllamaBaseUrlDraft] = useState<string>("");
  const [ollamaModelDraft, setOllamaModelDraft] = useState<string>("");
  const [hfEnabledDraft, setHfEnabledDraft] = useState<boolean>(false);
  const [hfBaseUrlDraft, setHfBaseUrlDraft] = useState<string>("");
  const [hfModelDraft, setHfModelDraft] = useState<string>("");
  const [hfTokenDraft, setHfTokenDraft] = useState<string>("");
  const [hfTokenMasked, setHfTokenMasked] = useState<string>("");
  const [llmEffective, setLlmEffective] = useState<any>(null);
  const [diagSaving, setDiagSaving] = useState(false);

  const [historyModalOpen, setHistoryModalOpen] = useState(false);

  const activeRegenByModuleId = useMemo(() => {
    const out: Record<string, { job_id: string; status: string; stage: string }> = {};
    for (const it of regenHistory || []) {
      const mid = String((it as any)?.module_id || "").trim();
      const jid = String((it as any)?.job_id || "").trim();
      const st = String((it as any)?.status || "").trim();
      const stage = String((it as any)?.stage || "").trim();
      if (!mid || !jid) continue;
      const stl = st.toLowerCase();
      const stagel = stage.toLowerCase();
      const terminal = stl === "finished" || stl === "failed" || stl === "canceled" || stagel === "canceled" || stagel === "done";
      if (!terminal) out[mid] = { job_id: jid, status: st, stage };
    }
    return out;
  }, [regenHistory]);

  const importLockedInfo = useMemo(() => {
    const anyRegen = Object.keys(activeRegenByModuleId || {}).length > 0;
    const st = String(jobStatus || "");
    const stage = String(jobStage || "");
    const jobTerminal = st === "finished" || st === "failed" || stage === "canceled";
    const importJobRunning = jobPanelOpen && !!selectedJobId && !jobTerminal;

    const stageHuman = (() => {
      const s = stage.trim().toLowerCase();
      if (!s) return "—";
      if (s === "start") return "СТАРТ";
      if (s === "download") return "СКАЧИВАНИЕ";
      if (s === "extract") return "РАСПАКОВКА";
      if (s === "import") return "ИМПОРТ";
      if (s === "ai" || s === "ollama") return "НЕЙРОСЕТЬ";
      if (s === "replace") return "ГЕНЕРАЦИЯ";
      if (s === "commit") return "СОХРАНЕНИЕ";
      if (s === "cleanup") return "ОЧИСТКА";
      if (s === "done") return "ГОТОВО";
      if (s === "failed") return "ОШИБКА";
      return s.toUpperCase();
    })();

    const locked = !!importBusy || importJobRunning || anyRegen;
    let reason = "";
    if (!locked) return { locked: false, reason };

    if (importBusy) reason = "ИДЁТ ЗАПУСК ИМПОРТА";
    else if (importJobRunning) reason = `ИДЁТ ИМПОРТ: ${stageHuman}`;
    else if (anyRegen) reason = "ИДЁТ РЕГЕН ТЕСТОВ";
    else reason = "СИСТЕМА ЗАНЯТА";

    return { locked: true, reason };
  }, [activeRegenByModuleId, importBusy, jobPanelOpen, selectedJobId, jobStatus, jobStage]);

  async function loadRegenHistory(silent: boolean = false) {
    try {
      if (!silent) setRegenHistoryLoading(true);
      const res = await apiFetch<{ items: any[] }>(`/admin/regen-jobs?limit=20`);
      const next = Array.isArray(res?.items) ? res.items : [];
      const sig = JSON.stringify(next);
      if (sig !== regenHistorySigRef.current) {
        regenHistorySigRef.current = sig;
        setRegenHistory(next);
      }
    } catch {
      setRegenHistory([]);
    } finally {
      if (!silent) setRegenHistoryLoading(false);
    }
  }

  const regenQueue = useMemo(() => {
    const items: RegenJobItem[] = [];
    for (const it of regenHistory || []) {
      const jid = String((it as any)?.job_id || (it as any)?.id || "").trim();
      if (!jid) continue;
      const st = String((it as any)?.status || "").trim();
      const stage = String((it as any)?.stage || "").trim();
      const stl = st.toLowerCase();
      const stagel = stage.toLowerCase();
      const terminal =
        stl === "finished" ||
        stl === "failed" ||
        stl === "canceled" ||
        stagel === "canceled" ||
        stagel === "done";
      if (terminal) continue;
      items.push({
        job_id: jid,
        module_id: String((it as any)?.module_id || "") || undefined,
        module_title: String((it as any)?.module_title || "") || undefined,
        target_questions: typeof (it as any)?.target_questions === "number" ? (it as any).target_questions : undefined,
        created_at: String((it as any)?.created_at || "") || undefined,
        status: st || undefined,
        stage: stage || undefined,
        detail: String((it as any)?.detail || "") || undefined,
        error_code: String((it as any)?.error_code || "") || undefined,
        error_hint: String((it as any)?.error_hint || "") || undefined,
        error_message: String((it as any)?.error_message || "") || undefined,
        error: (it as any)?.error ? String((it as any).error) : null,
      });
    }
    return items;
  }, [regenHistory]);

  async function loadRuntimeLlmSettings() {
    try {
      const data = await apiFetch<any>("/admin/runtime/llm");
      setLlmOrderDraft(String(data?.llm_provider_order || ""));
      setOllamaEnabledDraft(!!data?.ollama_enabled);
      setOllamaBaseUrlDraft(String(data?.ollama_base_url || ""));
      setOllamaModelDraft(String(data?.ollama_model || ""));
      setHfEnabledDraft(!!data?.hf_router_enabled);
      setHfBaseUrlDraft(String(data?.hf_router_base_url || ""));
      setHfModelDraft(String(data?.hf_router_model || ""));
      setHfTokenDraft("");
      setHfTokenMasked(String(data?.hf_router_token_masked || ""));
      setLlmEffective(data?.effective || null);
    } catch {
      // ignore
    }
  }

  async function clearRuntimeHfToken() {
    const ok = window.confirm("Очистить HF token? Генерация через HF Router перестанет работать.");
    if (!ok) return;
    try {
      setDiagSaving(true);
      setError(null);
      await apiFetch<any>("/admin/runtime/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hf_router_token: "" }),
      } as any);
      await loadRuntimeLlmSettings();
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: { title: "ДИАГНОСТИКА", description: "TOKEN ОЧИЩЕН" },
        })
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ ОЧИСТИТЬ TOKEN");
    } finally {
      setDiagSaving(false);
    }
  }

  async function saveRuntimeLlmSettings() {
    try {
      setDiagSaving(true);
      setError(null);
      const body: any = {
        llm_provider_order: (llmOrderDraft || "").trim(),
        ollama_enabled: !!ollamaEnabledDraft,
        ollama_base_url: (ollamaBaseUrlDraft || "").trim(),
        ollama_model: (ollamaModelDraft || "").trim(),
        hf_router_enabled: !!hfEnabledDraft,
        hf_router_base_url: (hfBaseUrlDraft || "").trim(),
        hf_router_model: (hfModelDraft || "").trim(),
      };
      const tok = (hfTokenDraft || "").trim();
      if (tok) body.hf_router_token = tok;

      await apiFetch<any>("/admin/runtime/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      } as any);
      await loadSystemStatus();
      await loadRuntimeLlmSettings();
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: { title: "ДИАГНОСТИКА", description: "НАСТРОЙКИ СОХРАНЕНЫ" },
        })
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ СОХРАНИТЬ НАСТРОЙКИ");
    } finally {
      setDiagSaving(false);
    }
  }

  async function setSelectedModuleVisibility(nextActive: boolean) {
    if (!selectedAdminModuleId) return;
    try {
      setError(null);
      await apiFetch<any>(`/admin/modules/${encodeURIComponent(selectedAdminModuleId)}/visibility`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !!nextActive }),
      } as any);
      await loadAdminModules();
      await reloadModules();
      await loadSelectedAdminModule();
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: {
            title: nextActive ? "МОДУЛЬ ОПУБЛИКОВАН" : "МОДУЛЬ СКРЫТ",
            description: "",
          },
        })
      );
    } catch (e) {
      const anyErr: any = e as any;
      const status = Number(anyErr?.status || 0);
      const code = String(anyErr?.errorCode || "").trim();
      const msg = e instanceof Error ? e.message : String(e);
      const raw = String(msg || "").trim();

      if (status === 409 && code === "MODULE_NOT_READY") {
        window.dispatchEvent(
          new CustomEvent("corelms:toast", {
            detail: {
              title: "МОДУЛЬ НЕ ГОТОВ",
              description: raw || "Запустите РЕГЕН ТЕСТОВ и дождитесь завершения.",
            },
          })
        );
        return;
      }

      setError(raw || "НЕ УДАЛОСЬ ИЗМЕНИТЬ ВИДИМОСТЬ МОДУЛЯ");
    }
  }

  async function reloadModules() {
    const ms = await apiFetch<any[]>(`/modules`);
    const mapped = (ms || []).map((m) => ({ id: String(m.id), title: String(m.title) }));
    setModules(mapped);
    if (mapped.length && (!moduleId || !mapped.some((x) => x.id === moduleId))) {
      setModuleId(mapped[0].id);
    }
  }

  useEffect(() => {
    if (tab !== "modules") return;
    void loadRegenHistory(false);
    const t = window.setInterval(() => {
      void loadImportQueue(20, false, true);
      void loadRegenHistory(true);
    }, 4000);
    return () => window.clearInterval(t);
  }, [tab]);

  async function cancelCurrentJob() {
    if (String(jobKind || "").toLowerCase() === "regen") {
      const id = String(selectedJobId || "").trim();
      if (!id) return;
      await cancelRegenJob(id);
      return;
    }

    if (!selectedJobId && importBatchJobIdsRef.current.length === 0) return;
    try {
      setCancelBusy(true);
      importCancelRequestedRef.current = true;
      setClientImportStage("canceled");

      try {
        if (importUploadAbortRef.current) {
          importUploadAbortRef.current.abort();
        }
      } catch {
        // ignore
      }

      try {
        const objKey = String(importUploadObjectKeyRef.current || "").trim();
        const fn = String(importUploadFilenameRef.current || "").trim();
        if (objKey) {
          await apiFetch<any>(`/admin/modules/abort-import-zip` as any, {
            method: "POST",
            body: JSON.stringify({ object_key: objKey, filename: fn || null }),
          } as any);
        }
      } catch {
        // ignore
      }

      const ids = (importBatchJobIdsRef.current.length ? importBatchJobIdsRef.current : [selectedJobId])
        .map((x) => String(x || "").trim())
        .filter(Boolean);
      await Promise.all(
        ids.map((id) => apiFetch<any>(`/admin/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" }))
      );
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: {
            title: "ОТМЕНА ЗАПРОШЕНА",
            description: ids.length > 1 ? `BATCH: ${ids.length} JOBS` : "ЗАДАЧА БУДЕТ ОСТАНОВЛЕНА, ZIP ОСТАНЕТСЯ В STORAGE",
          },
        })
      );
      saveImportState({ cancelRequested: true });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ ОТМЕНИТЬ JOB");
    } finally {
      setCancelBusy(false);
    }
  }

  async function loadAdminModules() {
    try {
      setAdminModulesLoading(true);
      const res = await apiFetch<{ items: AdminModuleItem[] }>(`/admin/modules`);
      const items = (res?.items || [])
        .map((m) => ({
          id: String(m.id),
          title: String(m.title || ""),
          is_active: !!(m as any).is_active,
          final_quiz_id: (m as any).final_quiz_id ? String((m as any).final_quiz_id) : null,
          category: (m as any).category ?? null,
          difficulty: typeof (m as any).difficulty === "number" ? (m as any).difficulty : null,
          question_quality:
            (m as any).question_quality && typeof (m as any).question_quality === "object"
              ? {
                  total_current: Number((m as any).question_quality.total_current || 0),
                  needs_regen_current: Number((m as any).question_quality.needs_regen_current || 0),
                  fallback_current: Number((m as any).question_quality.fallback_current || 0),
                  ai_current: Number((m as any).question_quality.ai_current || 0),
                  heur_current: Number((m as any).question_quality.heur_current || 0),
                }
              : undefined,
        }))
        .sort((a, b) => {
          if (a.is_active !== b.is_active) return a.is_active ? -1 : 1;
          return String(a.title || "").localeCompare(String(b.title || ""));
        });

      setAdminModules(items);
      if (items.length && (!selectedAdminModuleId || !items.some((x) => x.id === selectedAdminModuleId))) {
        setSelectedAdminModuleId(items[0].id);
      }
    } finally {
      setAdminModulesLoading(false);
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
        setSelectedSubmoduleId(sorted[0].id);
        setSelectedQuizId(String(sorted[0].quiz_id || ""));
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
      setSubQualityLoadingByModuleId((prev) => ({ ...prev, [mid]: true }));
      const res = await apiFetch<{ ok: boolean; module_id: string; items: AdminSubmoduleQualityItem[] }>(
        `/admin/modules/${encodeURIComponent(mid)}/submodules/quality`
      );
      const items = Array.isArray(res?.items) ? res.items : [];
      setSubQualityByModuleId((prev) => ({ ...prev, [mid]: items }));
    } catch {
      setSubQualityByModuleId((prev) => ({ ...prev, [mid]: [] }));
    } finally {
      setSubQualityLoadingByModuleId((prev) => ({ ...prev, [mid]: false }));
    }
  }

  async function regenerateSubmoduleQuiz(submoduleId: string) {
    const sid = String(submoduleId || "").trim();
    if (!sid) return;
    try {
      setError(null);

      // UX: the unified job panel lives in the Import tab.
      setTab("import");
      setJobPanelOpen(true);

      const forceAi = window.confirm(
        "ФОРСИРОВАТЬ AI ДЛЯ ЭТОГО УРОКА?\n\nЕсли включить — вопросы будут только от нейронки. Если AI не сработает — задача упадёт с ошибкой."
      );
      const res = await apiFetch<{ ok: boolean; job_id: string }>(
        `/admin/submodules/${encodeURIComponent(sid)}/regenerate-quiz?target_questions=5&force_ai=${forceAi ? "1" : "0"}`,
        {
          method: "POST",
        }
      );
      void res;
      await Promise.all([
        loadRegenHistory(true),
        loadAdminModules(),
        loadSelectedAdminModule(),
        loadImportQueue(20, false, true),
      ]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ ЗАПУСТИТЬ РЕГЕН УРОКА");
    }
  }

  async function loadQuestionsForQuiz(quizId: string) {
    const qid = String(quizId || "").trim();
    if (!qid) return;
    try {
      setQuestionsLoadingQuizId(qid);
      const res = await apiFetch<{ items: AdminQuestionItem[] }>(`/admin/quizzes/${encodeURIComponent(qid)}/questions`);
      setQuestionsByQuizId((prev) => ({ ...prev, [qid]: (res?.items || []) as AdminQuestionItem[] }));
    } finally {
      setQuestionsLoadingQuizId("");
    }
  }

  async function saveQuestionPatch(questionId: string, patch: Partial<AdminQuestionItem>) {
    const id = String(questionId || "").trim();
    if (!id) return;
    try {
      setQuestionSavingId(id);
      const res = await apiFetch<any>(`/admin/questions/${encodeURIComponent(id)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch),
        }
      );
      const item = (res && res.item) ? (res.item as AdminQuestionItem) : null;
      if (item?.quiz_id) {
        setQuestionsByQuizId((prev) => {
          const list = (prev[String(item.quiz_id)] || []).slice();
          const idx = list.findIndex((q) => String(q.id) === String(item.id));
          if (idx >= 0) list[idx] = item;
          return { ...prev, [String(item.quiz_id)]: list };
        });
      }
    } finally {
      setQuestionSavingId("");
    }
  }

  function getDraftValue(q: any, key: string): any {
    const qid = String(q.id);
    const draft = questionDraftsById[qid];
    if (draft && typeof draft[key as keyof AdminQuestionItem] !== "undefined") {
      return draft[key as keyof AdminQuestionItem];
    }
    return q[key as keyof AdminQuestionItem];
  }

  function isQuestionDirty(q: AdminQuestionItem): boolean {
    const d = questionDraftsById[String(q.id)] || {};
    const keys = Object.keys(d);
    if (!keys.length) return false;
    for (const k of keys) {
      const kk = k as keyof AdminQuestionItem;
      const dv = (d as any)[kk];
      const ov = (q as any)[kk];
      if (String(dv ?? "") !== String(ov ?? "")) return true;
    }
    return false;
  }

  async function saveQuestionDraft(questionId: string) {
    const id = String(questionId || "").trim();
    if (!id) return;
    const draft = questionDraftsById[id];
    if (!draft || !Object.keys(draft).length) return;
    const patch: Partial<AdminQuestionItem> = {};
    for (const [k, v] of Object.entries(draft)) {
      (patch as any)[k] = v;
    }
    if (typeof (patch as any).correct_answer === "string") {
      (patch as any).correct_answer = String((patch as any).correct_answer).trim();
    }
    await saveQuestionPatch(id, patch);
    setQuestionDraftsById((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  async function deleteQuestionAdmin(questionId: string) {
    const id = String(questionId || "").trim();
    if (!id) return;
    await apiFetch<any>(`/admin/questions/${encodeURIComponent(id)}`, { method: "DELETE" });
    setQuestionsByQuizId((prev) => {
      const next = { ...prev };
      for (const k of Object.keys(next)) {
        next[k] = (next[k] || []).filter((q) => String(q.id) !== id);
      }
      return next;
    });
    setQuestionDraftsById((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  async function createQuestionAdmin(quizId: string) {
    const qid = String(quizId || "").trim();
    if (!qid) return;
    try {
      setNewQuestionBusy(true);
      const res = await apiFetch<{ id: string }>(`/admin/questions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          quiz_id: qid,
          type: "single",
          difficulty: 1,
          prompt: "",
          correct_answer: "",
          explanation: null,
          concept_tag: null,
          variant_group: null,
        }),
      });
      const newId = String((res as any)?.id || "").trim();
      if (newId) {
        await loadQuestionsForQuiz(qid);
      }
    } finally {
      setNewQuestionBusy(false);
    }
  }

  async function regenerateSelectedModuleQuizzes() {
    if (!selectedAdminModuleId) return;
    const ok = window.confirm("Запустить регенерацию тестов для ВСЕГО модуля?\n\nГенерация займёт время.");
    if (!ok) return;
    try {
      setError(null);

      // UX: the unified job panel lives in the Import tab.
      setTab("import");
      setJobPanelOpen(true);

      const forceAi = window.confirm(
        "ФОРСИРОВАТЬ AI?\n\nЕсли включить — вопросы будут только от нейронки. Если AI недоступен или формат ответа неверный — задача упадёт с ошибкой (без heuristic)."
      );

      const res = await apiFetch<{ ok: boolean; job_id: string }>(
        `/admin/modules/${encodeURIComponent(selectedAdminModuleId)}/regenerate-quizzes?target_questions=5&force_ai=${forceAi ? "1" : "0"}`,
        {
          method: "POST",
        }
      );
      const jid = String((res as any)?.job_id || "").trim();
      if (jid) {
        setSelectedJobId(jid);
        setJobStatus("queued");
        setJobStage("queued");
        setJobStageAt("");
        setJobStageStartedAt("");
        setJobStageDurations(null);
        setJobStartedAt("");
        setJobDetail("");
        setJobError("");
        setJobErrorCode("");
        setJobErrorHint("");
        setJobResult(null);
        setJobPanelOpen(true);
      }

      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: {
            title: "РЕГЕНЕРАЦИЯ ТЕСТОВ",
            description: jid ? `JOB: ${jid}` : "ЗАДАЧА ДОБАВЛЕНА В ОЧЕРЕДЬ",
          },
        })
      );

      void loadRegenHistory(true);
      void loadImportQueue(20, false, true);
      void loadAdminModules();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ ЗАПУСТИТЬ РЕГЕНЕРАЦИЮ");
    }
  }

  const stageLabel = useMemo(() => {
    const s = (jobStage || "").toLowerCase();
    if (!s) return "";
    if (s === "start") return "ИНИЦИАЛИЗАЦИЯ";
    if (s === "load") return "ПОДГОТОВКА";
    if (s === "download") return "СКАЧИВАНИЕ";
    if (s === "extract") return "РАСПАКОВКА";
    if (s === "import") return "ИМПОРТ  БД";
    if (s === "ollama") return "AI: ЕНЕРАЦИЯ";
    if (s === "fallback") return "AI: FALLBACK";
    if (s === "replace") return "ОБНОЛЕНИЕ ОПРОСО";
    if (s === "commit") return "СОХРАНЕНИЕ";
    if (s === "cleanup") return "ОЧИСТКА";
    if (s === "done") return "ОТОО";
    if (s === "failed") return "ОШИБКА";
    return s.toUpperCase();
  }, [jobStage]);

  const importStageLabel = useMemo(() => {
    const st = String(clientImportStage || "").trim().toLowerCase();
    if (!st) return "—";
    if (st === "upload") return "ЗАГРУЗКА";
    if (st === "upload_s3") return "STORAGE";
    if (st === "enqueue") return "ОЧЕРЕДЬ";
    if (st === "processing") return "ОБРАБОТКА";
    if (st === "skipped") return "ПРОПУЩЕНО";
    if (st === "canceled") return "ОТМЕНЕНО";
    if (st === "failed") return "ОШИБКА";
    if (st === "done") return "ГОТОВО";
    return st.toUpperCase();
  }, [clientImportStage]);

  const importJobStageLabel = useMemo(() => {
    const st = String(jobStage || "").trim().toLowerCase();
    if (!st) return "—";
    if (st === "start") return "СТАРТ";
    if (st === "download") return "СКАЧИВАНИЕ";
    if (st === "extract") return "РАСПАКОВКА";
    if (st === "import") return "ИМПОРТ";
    if (st === "ai" || st === "ollama") return "НЕЙРОСЕТЬ";
    if (st === "replace") return "ГЕНЕРАЦИЯ";
    if (st === "commit") return "СОХРАНЕНИЕ";
    if (st === "cleanup") return "ОЧИСТКА";
    if (st === "done") return "ГОТОВО";
    if (st === "failed") return "ОШИБКА";
    return stageLabel || st.toUpperCase();
  }, [jobStage, stageLabel]);

  async function loadSystemStatus() {
    try {
      setSysLoading(true);
      const data = await apiFetch<any>("/admin/system/status");
      setSys(data);
    } catch {
      setSys(null);
    } finally {
      setSysLoading(false);
    }
  }

  async function retryImport(jobId: string) {
    const id = (jobId || "").trim();
    if (!id) return;
    try {
      setError(null);
      const res = await apiFetch<{ ok: boolean; job_id: string }>(
        `/admin/import-jobs/${encodeURIComponent(id)}/retry`,
        {
          method: "POST",
        }
      );
      const newId = String(res.job_id || "");
      if (newId) {
        setSelectedJobId(newId);
        setJobStage("queued");
        setJobDetail("");
        setJobError("");
        setJobPanelOpen(true);
      }
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: {
            title: "ИМПОРТ ПОВТОРЁН",
            description: newId ? `JOB: ${newId}` : "ЗАДАЧА ПЕРЕСОЗДАНА",
          },
        })
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ ПОВТОРИТЬ ИМПОРТ");
    }
  }

  useEffect(() => {
    (async () => {
      try {
        setError(null);
        await reloadModules();
        await loadAdminModules();
        await loadRegenHistory(false);
      } catch {
        setError("НЕ УДАЛОСЬ ЗАРУЗИТЬ СПИСОК МОДУЛЕЙ");
      }
    })();
  }, []);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(IMPORT_STATE_KEY);
      if (!raw) return;
      const st = JSON.parse(raw);
      const jid = String(st?.selectedJobId || "").trim();
      const ids = Array.isArray(st?.importBatchJobIds)
        ? st.importBatchJobIds.map((x: any) => String(x || "").trim()).filter(Boolean)
        : [];
      if (ids.length) importBatchJobIdsRef.current = ids;
      if (jid) setSelectedJobId(jid);
      if (typeof st?.jobPanelOpen === "boolean") setJobPanelOpen(!!st.jobPanelOpen);
      if (st?.clientImportStage) setClientImportStage(String(st.clientImportStage || ""));
      if (st?.clientImportFileName) setClientImportFileName(String(st.clientImportFileName || ""));
    } catch {
      // ignore
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const ids = Array.from(new Set(importBatchJobIdsRef.current || [])).filter(Boolean);
    if (!jobPanelOpen && !selectedJobId && !ids.length) {
      clearImportState();
      return;
    }
    if (jobPanelOpen || selectedJobId || ids.length) {
      saveImportState();
    }
  }, [jobPanelOpen, selectedJobId, clientImportStage, clientImportFileName]);

  useEffect(() => {
    if (tab !== "modules") return;
    void loadAdminModules();
  }, [tab]);

  useEffect(() => {
    if (tab !== "modules") return;
    void loadSelectedAdminModule();
    setQuestionsByQuizId({});
  }, [tab, selectedAdminModuleId]);

  useEffect(() => {
    const qid = String(selectedQuizId || "").trim();
    if (!qid) return;
    void loadQuestionsForQuiz(qid);
  }, [selectedQuizId]);

  useEffect(() => {
    if (authLoading) return;
    if (user?.role !== "admin") return;
    void loadSystemStatus();
  }, [authLoading, user?.role]);

  useEffect(() => {
    if (!selectedJobId) return;
    if (!jobPanelOpen) return;
    let alive = true;
    let timer: any = null;
    let delayMs = 1000;
    const tick = async () => {
      try {
        const s = await apiFetch<any>(`/admin/jobs/${encodeURIComponent(selectedJobId)}`);
        if (!alive) return;
        setJobStatus(String(s?.status || ""));
        setJobStage(String(s?.stage || ""));
        setJobStageAt(String(s?.stage_at || ""));
        setJobStageStartedAt(String(s?.stage_started_at || ""));
        setJobStageDurations((s?.stage_durations_s as any) ?? null);
        setJobStartedAt(String(s?.job_started_at || s?.started_at || ""));
        setJobDetail(String(s?.detail || ""));
        setJobError(String(s?.error || s?.error_message || ""));
        setJobErrorCode(String(s?.error_code || ""));
        setJobErrorHint(String(s?.error_hint || ""));
        setJobResult(s?.result ?? null);
        setJobKind(String(s?.job_kind || ""));
        setJobModuleTitle(String(s?.module_title || ""));
        setJobModuleId(String(s?.module_id || ""));

        const st = String(s?.status || "");
        const terminal = st === "finished" || st === "failed" || String(s?.stage || "") === "canceled";
        if (terminal) {
          saveImportState({ terminal: true });
          void loadRegenHistory(true);
          void loadAdminModules();
          void reloadModules();
          if (selectedQuizId) {
            void loadQuestionsForQuiz(selectedQuizId);
          }

          // Two-phase import: if import finished and has a follow-up regen job id, switch panel to regen progress.
          try {
            const maybeRegenJobId = String((s?.result as any)?.regen_job_id || "").trim();
            const hasImportReport = !!(s?.result as any)?.report;
            if (st === "finished" && hasImportReport && maybeRegenJobId && maybeRegenJobId !== selectedJobId) {
              setSelectedJobId(maybeRegenJobId);
              setJobStatus("queued");
              setJobStage("queued");
              setJobStageAt("");
              setJobStageStartedAt("");
              setJobStageDurations(null);
              setJobStartedAt("");
              setJobDetail("");
              setJobError("");
              setJobErrorCode("");
              setJobErrorHint("");
              setJobResult(null);
              setJobPanelOpen(true);
              saveImportState({ followup_regen_job_id: maybeRegenJobId });
            }
          } catch {
            // ignore
          }
          return;
        }
      } catch (e) {
        if (!alive) return;
        const msg = e instanceof Error ? e.message : String(e);
        setJobError(msg || "НЕ УДАЛОСЬ ПОЛУЧИТЬ СТАТУС JOB");
      }

      delayMs = Math.min(7000, Math.floor(delayMs * 1.15));
      timer = window.setTimeout(() => void tick(), delayMs);
    };

    void tick();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [jobPanelOpen, selectedJobId, selectedQuizId]);

  useEffect(() => {
    (async () => {
      if (!moduleId) return;
      try {
        setError(null);
        const r = await apiFetch<Report>(`/admin/analytics/modules/${moduleId}`);
        setReport(r);
      } catch {
        setError("НЕ УДАЛОСЬ ЗАРУЗИТЬ ОТЧЁТ");
      }
    })();
  }, [moduleId]);

  useEffect(() => {
    (async () => {
      if (tab !== "analytics") return;
      if (analyticsMode !== "content") return;
      if (!moduleId) return;
      try {
        setQualityLoading(true);
        const res = await apiFetch<{ items: QuestionQualityItem[] }>(
          `/admin/analytics/modules/${encodeURIComponent(moduleId)}/question-quality?limit=50`
        );
        setQuality(Array.isArray(res.items) ? res.items : []);
      } catch {
        setQuality([]);
      } finally {
        setQualityLoading(false);
      }
    })();
  }, [tab, analyticsMode, moduleId]);

  function exportQualityCsv() {
    const rows = quality || [];
    const headers = [
      "failure_rate",
      "total",
      "incorrect",
      "quiz_type",
      "question_type",
      "concept_tag",
      "question_id",
      "prompt",
    ];
    const esc = (v: any) => {
      const s = String(v ?? "");
      return `"${s.replace(/"/g, '""')}"`;
    };
    const lines = [headers.join(",")].concat(
      rows.map((r) =>
        [
          r.failure_rate,
          r.total,
          r.incorrect,
          r.quiz_type,
          r.type,
          r.concept_tag ?? "",
          r.question_id,
          (r.prompt || "").replace(/\s+/g, " ").slice(0, 500),
        ]
          .map(esc)
          .join(",")
      )
    );

    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `corelms-module-${moduleId}-question-quality.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function startImport() {
    if (!importFiles.length) {
      setError("ВЫБЕРИТЕ ZIP-ФАЙЛЫ");
      return;
    }

    const files = [...importFiles];
    setImportFiles([]);

    try {
      if (importInputRef.current) {
        importInputRef.current.value = "";
      }
    } catch {
      // ignore
    }

    const deriveTitleFromZipName = (name: string): string => {
      const raw = String(name || "").trim();
      const base = raw.toLowerCase().endsWith(".zip") ? raw.slice(0, -4) : raw;
      const cleaned = base
        .replace(/[_\-]+/g, " ")
        .replace(/\s+/g, " ")
        .replace(/\.+/g, ".")
        .trim();
      return cleaned;
    };

    const existingTitlesLower = new Set(
      (adminModules || [])
        .map((m) => String(m.title || "").trim().toLowerCase())
        .filter(Boolean)
    );

    try {
      setImportBusy(true);
      setError(null);

      const keepAlive = () => {
        try {
          window.dispatchEvent(new Event("corelms:keepalive"));
        } catch {
          // ignore
        }
      };

      const uploadS3WithProgress = async (url: string, file: File, ac: AbortController) => {
        setS3UploadProgress({
          loaded: 0,
          total: Math.max(0, Number((file as any)?.size || 0)),
          startedAtMs: Date.now(),
          lastAtMs: Date.now(),
          lastLoaded: 0,
          speedBps: 0,
          etaSeconds: null,
          percent: 0,
        });

        await new Promise<void>((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          let done = false;

          const finish = (err?: unknown) => {
            if (done) return;
            done = true;
            try {
              ac.signal.removeEventListener("abort", onAbort);
            } catch {
              // ignore
            }
            if (err) reject(err);
            else resolve();
          };

          const onAbort = () => {
            try {
              xhr.abort();
            } catch {
              // ignore
            }
            finish(new DOMException("Aborted", "AbortError"));
          };

          try {
            ac.signal.addEventListener("abort", onAbort);
          } catch {
            // ignore
          }

          xhr.open("PUT", String(url || ""), true);
          xhr.upload.onprogress = (evt) => {
            if (!evt || !evt.lengthComputable) return;
            const now = Date.now();
            const loaded = Math.max(0, Number(evt.loaded || 0));
            const total = Math.max(1, Number(evt.total || 1));
            setS3UploadProgress((prev) => {
              const startedAtMs = prev?.startedAtMs ?? now;
              const lastAtMs = prev?.lastAtMs ?? startedAtMs;
              const lastLoaded = prev?.lastLoaded ?? 0;
              const dt = Math.max(1, now - lastAtMs);
              const dbytes = Math.max(0, loaded - lastLoaded);
              const instSpeed = (dbytes * 1000) / dt;
              const speedBps = prev ? 0.7 * prev.speedBps + 0.3 * instSpeed : instSpeed;
              const remain = Math.max(0, total - loaded);
              const etaSeconds = speedBps > 1 ? Math.round(remain / speedBps) : null;
              const percent = Math.max(0, Math.min(100, Math.round((loaded / total) * 100)));
              return {
                loaded,
                total,
                startedAtMs,
                lastAtMs: now,
                lastLoaded: loaded,
                speedBps,
                etaSeconds,
                percent,
              };
            });
          };

          xhr.onerror = () => {
            finish(new Error("S3 upload failed: network error"));
          };
          xhr.onabort = () => {
            finish(new DOMException("Aborted", "AbortError"));
          };
          xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) {
              setS3UploadProgress((prev) => {
                if (!prev) return prev;
                return { ...prev, loaded: prev.total, percent: 100, etaSeconds: 0 };
              });
              finish();
              return;
            }
            const body = String(xhr.responseText || "").replace(/\s+/g, " ").slice(0, 320);
            finish(new Error(`S3 upload failed: HTTP ${xhr.status}${body ? ` body: ${body}` : ""}`));
          };

          try {
            xhr.send(file);
          } catch (e) {
            finish(e);
          }
        });
      };

      importBatchJobIdsRef.current = [];
      importCancelRequestedRef.current = false;
      setJobResult(null);
      setJobStatus("");
      setJobError("");
      setJobErrorCode("");
      setJobErrorHint("");
      setJobStage("");
      setJobStageAt("");
      setJobStageStartedAt("");
      setJobStageDurations(null);
      setJobStartedAt("");
      setJobDetail("");

      setSelectedJobId("");
      setClientImportStage("upload");
      setClientImportFileName(files.length === 1 ? String(files[0]?.name || "") : "");
      setJobPanelOpen(true);

      saveImportState({ started: true });

      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

      setImportEnqueueProgress({ total: files.length, done: 0 });
      setImportBatch({ total: files.length, done: 0 });
      let lastJobId = "";
      for (let idx = 0; idx < files.length; idx++) {
        if (importCancelRequestedRef.current) break;
        const f = files[idx];
        setClientImportStage("upload");
        setClientImportFileName(String(f?.name || ""));

        keepAlive();

        importUploadFilenameRef.current = String(f?.name || "");
        importUploadObjectKeyRef.current = "";
        importUploadAbortRef.current = null;
        setS3UploadProgress(null);

        const title = deriveTitleFromZipName(String(f?.name || ""));

        if (title && existingTitlesLower.has(String(title).trim().toLowerCase())) {
          window.dispatchEvent(
            new CustomEvent("corelms:toast", {
              detail: {
                title: "МОДУЛЬ УЖЕ ЕСТЬ",
                description: title ? title.toUpperCase() : "ДАННОЕ НАЗВАНИЕ УЖЕ СУЩЕСТВУЕТ",
              },
            })
          );
          setClientImportStage("skipped");
          setImportBatch((prev) => {
            if (!prev) return prev;
            return { ...prev, done: Math.min(prev.total, prev.done + 1) };
          });
          await new Promise<void>((resolve) => setTimeout(() => resolve(), 150));
          continue;
        }

        const form = new FormData();
        form.append("file", f);

        setClientImportStage("enqueue");
        let res: { ok: boolean; job_id: string } | null = null;
        try {
          const qs = title ? `?title=${encodeURIComponent(title)}` : "";
          // Ideal: upload large ZIPs directly to S3 to avoid Railway edge/proxy timeouts.
          // 1) presign
          const presign = await apiFetch<{ ok: boolean; object_key: string; upload_url: string | null; reused?: boolean }>(
            `/admin/modules/presign-import-zip` as any,
            {
              method: "POST",
              body: JSON.stringify({ filename: String(f?.name || "module.zip"), content_type: String((f as any)?.type || "application/zip") }),
            }
          );

          keepAlive();

          if (importCancelRequestedRef.current) {
            try {
              await apiFetch<any>(`/admin/modules/abort-import-zip` as any, {
                method: "POST",
                body: JSON.stringify({ object_key: String((presign as any)?.object_key || ""), filename: String(f?.name || "") }),
              } as any);
            } catch {
              // ignore
            }
            break;
          }

          importUploadObjectKeyRef.current = String((presign as any)?.object_key || "");

          if ((presign as any)?.reused) {
            window.dispatchEvent(
              new CustomEvent("corelms:toast", {
                detail: {
                  title: "ZIP УЖЕ ЗАГРУЖЕН",
                  description: "ПОВТОРНАЯ ЗАГРУЗКА НЕ НУЖНА — ИСПОЛЬЗУЮ STORAGE",
                },
              })
            );
          } else {
            // 2) upload to S3 (direct)
            setClientImportStage("upload_s3");
            const ac = new AbortController();
            importUploadAbortRef.current = ac;
            try {
              keepAlive();
              await uploadS3WithProgress(String(presign?.upload_url || ""), f, ac);
              keepAlive();
            } catch (e) {
              const objKey = String((presign as any)?.object_key || "").trim();
              const fn = String(f?.name || "module.zip");
              const base = e instanceof Error ? e.message : String(e);
              const hint =
                "S3/MinIO PUT не прошёл (браузер не получил ответ). Чаще всего это CORS (PUT) или неверный PUBLIC endpoint для S3. " +
                "Проверь DevTools → Network: запрос PUT (blocked by CORS / failed to fetch).";
              throw new Error(
                [
                  `S3 upload failed: ${base || "failed to fetch"}`,
                  fn ? `file: ${fn}` : "",
                  objKey ? `object_key: ${objKey}` : "",
                  hint,
                ]
                  .filter(Boolean)
                  .join("\n")
              );
            }

            setS3UploadProgress(null);
          }

          if (importCancelRequestedRef.current) {
            break;
          }

          // 3) enqueue import job
          setClientImportStage("enqueue");
          keepAlive();
          const enq = await apiFetch<{ ok: boolean; job_id: string }>(`/admin/modules/enqueue-import-zip${qs}` as any, {
            method: "POST",
            body: JSON.stringify({
              object_key: String(presign?.object_key || ""),
              title: title || null,
              source_filename: String(f?.name || ""),
            }),
          });
          keepAlive();
          res = { ok: true, job_id: String((enq as any)?.job_id || "") };

          // Perceived speed: reflect the job immediately.
          if (res?.job_id) {
            lastJobId = String(res.job_id);
            setSelectedJobId(String(res.job_id));
            setJobPanelOpen(true);
            // Silent refresh to avoid UI flicker.
            void loadImportQueue(20, false, true);
          }
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);

          // For large archives, do NOT fallback to legacy import (it will likely hit Railway 499/502).
          const isLargeZip = typeof (f as any)?.size === "number" && Number((f as any).size) > 50 * 1024 * 1024;
          const looksLikeS3UploadIssue =
            (msg || "").toLowerCase().includes("s3 upload failed") ||
            (msg || "").toLowerCase().includes("signature") ||
            (msg || "").toLowerCase().includes("failed to fetch") ||
            (msg || "").toLowerCase().includes("cors");

          if (isLargeZip && looksLikeS3UploadIssue) {
            const hint =
              "ЗАГРУЗКА В STORAGE НЕ ПРОШЛА. НУЖЕН CORS ДЛЯ BUCKET (PUT) ИЛИ ПРОБЛЕМА С PRESIGNED URL. " +
              "ОТКРОЙ DEVTOOLS → CONSOLE/NETWORK И ПРОВЕРЬ PUT НА S3.";
            setError((msg || "НЕ УДАЛОСЬ ЗАГРУЗИТЬ В STORAGE") + `\n${hint}`);
            setClientImportStage("failed");
            setImportBatch((prev) => {
              if (!prev) return prev;
              return { ...prev, done: Math.min(prev.total, prev.done + 1) };
            });
            await new Promise<void>((resolve) => setTimeout(() => resolve(), 150));
            continue;
          }

          // Fallback: legacy flow (works for small zips)
          try {
            const qs = title ? `?title=${encodeURIComponent(title)}` : "";
            res = await apiFetch<{ ok: boolean; job_id: string }>(`/admin/modules/import-zip${qs}` as any, {
              method: "POST",
              body: form,
            });
          } catch {
            // keep original handling below
          }
          if ((msg || "").toLowerCase().includes("409") || (msg || "").toLowerCase().includes("already exists")) {
            window.dispatchEvent(
              new CustomEvent("corelms:toast", {
                detail: {
                  title: "МОДУЛЬ УЖЕ ЕСТЬ",
                  description: title ? title.toUpperCase() : "ДАННОЕ НАЗАНИЕ УЖЕ СУЩЕСТВУЕТ",
                },
              })
            );
            setClientImportStage("skipped");
            setImportBatch((prev) => {
              if (!prev) return prev;
              return { ...prev, done: Math.min(prev.total, prev.done + 1) };
            });
            await new Promise<void>((resolve) => setTimeout(() => resolve(), 150));
            continue;
          }
          if (res && String((res as any).job_id || "").trim()) {
            // If fallback succeeded, continue the flow.
          } else {
            throw e;
          }
        }

        lastJobId = String(res?.job_id || "");
        if (lastJobId) {
          importBatchJobIdsRef.current.push(lastJobId);
          setSelectedJobId(lastJobId);
          setJobStatus("queued");
          setJobStage("start");
          setJobStageAt("");
          setJobStageStartedAt("");
          setJobStageDurations(null);
          setJobStartedAt("");
          setJobDetail("");
          setJobError("");
          setJobErrorCode("");
          setJobErrorHint("");
          setJobResult(null);
          saveImportState();
        }

        setImportEnqueueProgress((prev) => {
          if (!prev) return prev;
          return { ...prev, done: Math.min(prev.total, prev.done + 1) };
        });

        await new Promise<void>((resolve) => setTimeout(() => resolve(), 250));
      }

      // Important: do NOT mark as finished here. At this point we only enqueued jobs.
      // Real progress is driven by RQ job status/stage polling.
      setClientImportStage(importCancelRequestedRef.current ? "canceled" : "processing");
      void loadAdminModules();
      void reloadModules();
      void loadImportQueue(20, false, true);

      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: {
            title: "ИМПОРТ ЗАПУЩЕН",
            description: lastJobId ? `JOB: ${lastJobId}` : "ЗАДАЧИ ДОБАВЛЕНЫ В ОЧЕРЕДЬ",
          },
        })
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ ЗАПУСТИТЬ ИМПОРТ");
      setClientImportStage("failed");
    } finally {
      setImportBusy(false);
    }
  }

  // Track batch completion based on actual job statuses.
  useEffect(() => {
    if (!jobPanelOpen) return;
    const ids = Array.from(new Set(importBatchJobIdsRef.current || [])).filter(Boolean);
    if (!ids.length) return;

    let cancelled = false;
    let delayMs = 1500;
    let lastSig = "";
    const tick = async () => {
      try {
        const res = await Promise.all(
          ids.map((id) =>
            apiFetch<any>(`/admin/jobs/${encodeURIComponent(id)}`)
              .then((r) => ({ id, status: String(r?.status || ""), stage: String(r?.stage || "") }))
              .catch(() => ({ id, status: "", stage: "" }))
          )
        );

        if (cancelled) return;

        const sig = res
          .map((r) => `${r.id}:${r.status}:${r.stage}`)
          .sort()
          .join("|");
        if (sig !== lastSig) {
          lastSig = sig;
          delayMs = 1500;
        } else {
          delayMs = Math.min(7000, Math.floor(delayMs * 1.25));
        }

        const finishedCount = res.filter((r) => r.status === "finished").length;
        const failedCount = res.filter((r) => r.status === "failed").length;
        const canceledCount = res.filter((r) => r.stage === "canceled").length;
        const doneCount = finishedCount + failedCount + canceledCount;
        setImportBatch({ total: ids.length, done: Math.min(ids.length, doneCount) });

        if (doneCount >= ids.length) {
          if (failedCount > 0) setClientImportStage("failed");
          else if (canceledCount > 0) setClientImportStage("canceled");
          else setClientImportStage("done");
        }
      } catch {
        // ignore
        delayMs = Math.min(12000, Math.floor(delayMs * 1.6));
      }
    };

    void tick();
    let t: any = null;
    const loop = async () => {
      if (cancelled) return;
      await tick();
      if (cancelled) return;
      t = window.setTimeout(() => void loop(), delayMs);
    };
    t = window.setTimeout(() => void loop(), delayMs);
    return () => {
      cancelled = true;
      if (t) window.clearTimeout(t);
    };
  }, [jobPanelOpen]);

  async function copy(text: string) {
    const s = String(text || "");
    if (!s) return;
    try {
      await navigator.clipboard.writeText(s);
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: {
            title: "СКОПИРОАНО",
            description: s.length > 64 ? s.slice(0, 64) + "…" : s,
          },
        })
      );
    } catch {
      // noop
    }
  }

  async function deleteSelectedModule() {
    if (!selectedAdminModuleId) return;
    const ok = window.confirm("Удалить модуль? Действие необратимо.");
    if (!ok) return;
    try {
      setError(null);
      await apiFetch<any>(`/admin/modules/${encodeURIComponent(selectedAdminModuleId)}`, { method: "DELETE" });
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: { title: "МОДУЛЬ УДАЛЁН", description: "" },
        })
      );
      setSelectedAdminModuleId("");
      await loadAdminModules();
      await reloadModules();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ УДАЛИТЬ МОДУЛЬ");
    }
  }

  async function loadUsers() {
    try {
      setUsersLoading(true);
      const res = await apiFetch<{ items: UserItem[] }>(`/admin/users`);
      const items = Array.isArray(res?.items) ? res.items : [];
      setUsers(items);
      if (items.length && (!selectedUserId || !items.some((u) => String(u.id) === String(selectedUserId)))) {
        setSelectedUserId(String(items[0].id));
      }
    } catch {
      setUsers([]);
    } finally {
      setUsersLoading(false);
    }
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
        `/admin/users/${encodeURIComponent(id)}/history?limit=200`
      );
      setUserHistoryDetailed(Array.isArray(hist?.items) ? hist.items : []);
    } catch {
      setUserHistoryDetailed([]);
    } finally {
      setUserHistoryLoading(false);
    }
  }

  async function createUser() {
    const name = (newUserName || "").trim();
    if (!name) {
      setError("УКАЖИТЕ ИМЯ");
      return;
    }
    try {
      setNewUserBusy(true);
      setError(null);
      setNewUserTempPassword("");
      const res = await apiFetch<{ id: string; temp_password?: string | null }>(`/admin/users`, {
        method: "POST",
        body: JSON.stringify({
          name,
          position: (newUserPosition || "").trim() || null,
          role: newUserRole,
          must_change_password: true,
        }),
      });
      setNewUserTempPassword(String(res?.temp_password || ""));
      setNewUserName("");
      setNewUserPosition("");
      void loadUsers();
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: {
            title: "ПОЛЬЗОВАТЕЛЬ СОЗДАН",
            description: res?.temp_password ? "СОХРАНИТЕ ВРЕМЕННЫЙ ПАРОЛЬ" : "",
          },
        })
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ СОЗДАТЬ ПОЛЬЗОВАТЕЛЯ");
    } finally {
      setNewUserBusy(false);
    }
  }

  async function resetPassword() {
    if (!selectedUserId) return;
    const ok = window.confirm("СБРОСИТЬ ПАРОЛЬ ПОЛЬЗОВАТЕЛЮ? Будет выдан временный пароль.");
    if (!ok) return;
    try {
      setResetBusy(true);
      setError(null);
      setResetTempPassword("");
      const res = await apiFetch<{ ok: boolean; temp_password?: string | null }>(
        `/admin/users/${encodeURIComponent(selectedUserId)}/reset-password`,
        {
          method: "POST",
          body: JSON.stringify({ must_change_password: true }),
        }
      );
      setResetTempPassword(String(res?.temp_password || ""));
      void loadUserDetail(selectedUserId);
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: {
            title: "ПАРОЛЬ СБРОШЕН",
            description: res?.temp_password ? "ВЫДАН ВРЕМЕННЫЙ ПАРОЛЬ" : "",
          },
        })
      );
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
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: { title: "ПОЛЬЗОВАТЕЛЬ УДАЛЁН", description: "" },
        })
      );
      setSelectedUserId("");
      setUserDetail(null);
      await loadUsers();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ УДАЛИТЬ ПОЛЬЗОВАТЕЛЯ");
    } finally {
      setDeleteUserBusy(false);
    }
  }

  useEffect(() => {
    if (tab !== "users") return;
    void loadUsers();
  }, [tab]);

  useEffect(() => {
    if (tab !== "diagnostics") return;
    void loadSystemStatus();
    void loadRuntimeLlmSettings();
  }, [tab]);

  useEffect(() => {
    if (tab !== "users") return;
    void loadUserDetail(selectedUserId);
  }, [tab, selectedUserId]);

  const selectedAdminModule = useMemo(() => {
    return adminModules.find((m) => String(m.id) === String(selectedAdminModuleId)) || null;
  }, [adminModules, selectedAdminModuleId]);

  const selectedAdminModuleQuality = useMemo(() => {
    const q = (selectedAdminModule as any)?.question_quality;
    if (!q) {
      return {
        total_current: 0,
        needs_regen_current: 0,
        fallback_current: 0,
        ai_current: 0,
        heur_current: 0,
      };
    }
    return {
      total_current: Number(q.total_current || 0),
      needs_regen_current: Number(q.needs_regen_current || 0),
      fallback_current: Number(q.fallback_current || 0),
      ai_current: Number(q.ai_current || 0),
      heur_current: Number(q.heur_current || 0),
    };
  }, [selectedAdminModule]);

  const selectedQuizQuestions = useMemo(() => {
    const qid = String(selectedQuizId || "").trim();
    if (!qid) return [];
    return questionsByQuizId[qid] || [];
  }, [questionsByQuizId, selectedQuizId]);

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-7xl px-4 py-10">
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Каркас Тайги</div>
            <h1 className="mt-2 text-3xl font-black tracking-tighter text-zinc-950 uppercase">Админ-панель</h1>
          </div>
          <div className="flex items-center gap-2 rounded-2xl border border-zinc-200 bg-white p-2">
            {(
              [
                { key: "modules", label: "МОДУЛИ" },
                { key: "import", label: "ИМПОРТ" },
                { key: "analytics", label: "АНАЛИТИКА" },
                { key: "users", label: "ПОЛЬЗОВАТЕЛИ" },
                { key: "diagnostics", label: "ДИАГНОСТИКА" },
              ] as { key: TabKey; label: string }[]
            ).map((t) => {
              const active = tab === t.key;
              return (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setTab(t.key)}
                  className={
                    "h-10 rounded-xl px-4 text-[10px] font-black uppercase tracking-widest transition " +
                    (active
                      ? "bg-[#fe9900]/15 text-zinc-950 border border-[#fe9900]/25 border"
                      : "text-zinc-600 hover:text-zinc-950 hover:bg-zinc-50 border border-transparent")
                  }
                >
                  {t.label}
                </button>
              );
            })}
          </div>
        </div>

        {error ? (
          <div className="mt-6 rounded-[24px] border border-rose-200 bg-rose-50 p-5 text-sm font-bold text-rose-800">
            {error}
          </div>
        ) : tab === "diagnostics" ? (
          <DiagnosticsTab
            sys={sys}
            sysLoading={sysLoading}
            loadSystemStatus={loadSystemStatus}
            llmOrderDraft={llmOrderDraft}
            setLlmOrderDraft={setLlmOrderDraft}
            ollamaEnabledDraft={ollamaEnabledDraft}
            setOllamaEnabledDraft={setOllamaEnabledDraft}
            ollamaBaseUrlDraft={ollamaBaseUrlDraft}
            setOllamaBaseUrlDraft={setOllamaBaseUrlDraft}
            ollamaModelDraft={ollamaModelDraft}
            setOllamaModelDraft={setOllamaModelDraft}
            hfEnabledDraft={hfEnabledDraft}
            setHfEnabledDraft={setHfEnabledDraft}
            hfBaseUrlDraft={hfBaseUrlDraft}
            setHfBaseUrlDraft={setHfBaseUrlDraft}
            hfModelDraft={hfModelDraft}
            setHfModelDraft={setHfModelDraft}
            hfTokenDraft={hfTokenDraft}
            setHfTokenDraft={setHfTokenDraft}
            hfTokenMasked={hfTokenMasked}
            llmEffective={llmEffective}
            diagSaving={diagSaving}
            clearRuntimeHfToken={clearRuntimeHfToken}
            saveRuntimeLlmSettings={saveRuntimeLlmSettings}
            loadRuntimeLlmSettings={loadRuntimeLlmSettings}
          />
        ) : tab === "import" ? (
          <ImportTab
            importFiles={importFiles}
            importInputRef={importInputRef}
            setImportFiles={setImportFiles}
            importStageLabel={importStageLabel}
            s3UploadProgress={s3UploadProgress}
            importEnqueueProgress={importEnqueueProgress}
            importBatch={importBatch}
            importBusy={importBusy}
            startImport={startImport}
            importQueue={importQueue}
            importQueueLoading={importQueueLoading}
            loadImportQueue={loadImportQueue}
            setImportQueueView={setImportQueueView}
            setImportQueueModalOpen={setImportQueueModalOpen}
            importQueueModalOpen={importQueueModalOpen}
            importQueueView={importQueueView}
            importQueueHistory={importQueueHistory}
            setSelectedJobId={setSelectedJobId}
            setJobPanelOpen={setJobPanelOpen}
            cancelImportJob={cancelImportJob}
            retryImportJob={retryImportJob}
            openModuleFromImport={openModuleFromImport}
            regenQueue={regenQueue}
            regenHistoryLoading={regenHistoryLoading}
            loadRegenHistory={loadRegenHistory}
            setRegenQueueModalOpen={setRegenQueueModalOpen}
            regenQueueModalOpen={regenQueueModalOpen}
            regenHistory={regenHistory}
            jobPanelOpen={jobPanelOpen}
            selectedJobId={selectedJobId}
            jobStatus={jobStatus}
            jobStage={jobStage}
            importJobStageLabel={importJobStageLabel}
            copy={copy}
            cancelCurrentJob={cancelCurrentJob}
            cancelBusy={cancelBusy}
            jobKind={jobKind}
            jobModuleTitle={jobModuleTitle}
            jobDetail={jobDetail}
            jobError={jobError}
            jobErrorCode={jobErrorCode}
            jobErrorHint={jobErrorHint}
            clientImportStage={clientImportStage}
            clientImportFileName={clientImportFileName}
            selectedAdminModule={selectedAdminModule}
            selectedAdminModuleQuality={selectedAdminModuleQuality}
            jobResult={jobResult}
          />
        ) : tab === "modules" ? (
          <ModulesTab
            adminModules={adminModules}
            adminModulesLoading={adminModulesLoading}
            loadAdminModules={loadAdminModules}
            selectedAdminModuleId={selectedAdminModuleId}
            setSelectedAdminModuleId={setSelectedAdminModuleId}
            selectedAdminModule={selectedAdminModule}
            setSelectedModuleVisibility={setSelectedModuleVisibility}
            activeRegenByModuleId={activeRegenByModuleId}
            regenerateSelectedModuleQuizzes={regenerateSelectedModuleQuizzes}
            deleteSelectedModule={deleteSelectedModule}
            selectedAdminModuleSubsLoading={selectedAdminModuleSubsLoading}
            selectedAdminModuleSubs={selectedAdminModuleSubs}
            selectedAdminModuleSubsQuality={subQualityByModuleId[String(selectedAdminModuleId || "")] || []}
            selectedAdminModuleSubsQualityLoading={
              !!subQualityLoadingByModuleId[String(selectedAdminModuleId || "")]
            }
            regenerateSubmoduleQuiz={regenerateSubmoduleQuiz}
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
        ) : tab === "users" ? (
          <UsersTab
            newUserBusy={newUserBusy}
            createUser={createUser}
            newUserName={newUserName}
            setNewUserName={setNewUserName}
            newUserPosition={newUserPosition}
            setNewUserPosition={setNewUserPosition}
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
            resetBusy={resetBusy}
            resetPassword={resetPassword}
            deleteUserBusy={deleteUserBusy}
            deleteSelectedUser={deleteSelectedUser}
            userHistoryLoading={userHistoryLoading}
            userHistoryDetailed={userHistoryDetailed}
            setHistoryModalOpen={setHistoryModalOpen}
            resetTempPassword={resetTempPassword}
          />
        ) : tab === "analytics" ? (
          <div className="mt-8 space-y-6">
            <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-[28px] border border-zinc-200 bg-white p-6 shadow-sm">
                <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">Всего модулей</div>
                <div className="mt-3 flex items-baseline gap-2">
                  <div className="text-3xl font-black tracking-tighter text-zinc-950">{adminModules.length}</div>
                </div>
              </div>
              <div className="rounded-[28px] border border-zinc-200 bg-white p-6 shadow-sm">
                <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">Пользователей</div>
                <div className="mt-3 flex items-baseline gap-2">
                  <div className="text-3xl font-black tracking-tighter text-zinc-950">{users.length}</div>
                </div>
              </div>
              <div className="rounded-[28px] border border-zinc-200 bg-white p-6 shadow-sm">
                <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">Завершено обучений</div>
                <div className="mt-3 flex items-baseline gap-2">
                  <div className="text-3xl font-black tracking-tighter text-zinc-950">
                    {users.reduce((acc, u) => acc + (u.progress_summary?.completed_count || 0), 0)}
                  </div>
                </div>
              </div>
              <div className="rounded-[28px] border border-zinc-200 bg-white p-6 shadow-sm">
                <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">Активных сессий</div>
                <div className="mt-3 flex items-baseline gap-2">
                  <div className="text-3xl font-black tracking-tighter text-[#fe9900]">
                    {users.filter(u => u.last_activity_at && new Date(u.last_activity_at).getTime() > Date.now() - 24 * 60 * 60 * 1000).length}
                  </div>
                </div>
              </div>
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <div className="rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-8 shadow-xl">
                <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500 mb-6">Популярные модули</div>
                <div className="space-y-4">
                  {adminModules.slice(0, 5).map(m => {
                    const count = users.filter(u => 
                      u.progress_summary?.current?.module_id === m.id || 
                      (u.progress_summary?.completed_count || 0) > 0
                    ).length;
                    return (
                      <div key={m.id} className="flex items-center justify-between gap-4">
                        <div className="flex items-center gap-3">
                          <div className="h-8 w-8 rounded-lg bg-zinc-100 flex items-center justify-center text-[10px] font-black">
                            {m.title[0]}
                          </div>
                          <div className="text-sm font-bold text-zinc-950">{m.title}</div>
                        </div>
                        <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">
                          {count} чел.
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-8 shadow-xl">
                <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500 mb-6">Последняя активность</div>
                <div className="space-y-4">
                  {users
                    .filter(u => u.last_activity_at)
                    .sort((a, b) => new Date(b.last_activity_at!).getTime() - new Date(a.last_activity_at!).getTime())
                    .slice(0, 5)
                    .map(u => (
                      <div key={u.id} className="flex items-center justify-between gap-4">
                        <div className="flex items-center gap-3">
                          <div className="h-8 w-8 rounded-full bg-[#fe9900]/10 flex items-center justify-center text-[10px] font-black text-[#fe9900]">
                            {u.name[0]}
                          </div>
                          <div className="text-sm font-bold text-zinc-950">{u.name}</div>
                        </div>
                        <div className="text-[10px] font-black text-zinc-400 tabular-nums">
                          {new Date(u.last_activity_at!).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}
                        </div>
                      </div>
                    ))}
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      <Modal open={historyModalOpen} onClose={() => setHistoryModalOpen(false)}>
        <div className="p-6 sm:p-8 w-[min(92vw,760px)]">
          <div className="flex items-center justify-between gap-4 mb-6">
            <div>
              <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900]">АКТИВНОСТЬ</div>
              <h3 className="mt-1 text-2xl font-black tracking-tighter text-zinc-950 uppercase">Полная история</h3>
            </div>
            <button
              onClick={() => setHistoryModalOpen(false)}
              className="h-10 w-10 rounded-xl border border-zinc-200 bg-white flex items-center justify-center hover:bg-zinc-50 transition-colors"
            >
              <span className="text-xl font-light">×</span>
            </button>
          </div>

          <div className="space-y-3">
            {userHistoryLoading ? (
              <div className="py-12 text-center text-[11px] font-black uppercase tracking-widest text-zinc-400">
                Загрузка…
              </div>
            ) : (
              (userHistoryDetailed || []).map((h) => (
                <div key={h.id} className="group rounded-2xl border border-zinc-100 bg-zinc-50/50 p-4 transition-all hover:bg-white hover:border-[#fe9900]/20 hover:shadow-xl hover:shadow-zinc-950/5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="space-y-1 min-w-0">
                      <div className="text-[11px] font-black text-zinc-950 uppercase tracking-tight truncate">
                        {h.title}
                      </div>
                      {h.subtitle ? (
                        <div className="text-[10px] text-zinc-500 font-bold uppercase tracking-tight truncate">
                          {h.subtitle}
                        </div>
                      ) : null}
                      {(h.module_title || h.submodule_title || h.asset_name) ? (
                        <div className="text-[10px] text-zinc-500 font-bold uppercase tracking-tight">
                          {[h.module_title, h.submodule_title, h.asset_name].filter(Boolean).join(" · ")}
                        </div>
                      ) : null}
                      <div className="text-[10px] text-zinc-500 font-bold tabular-nums">
                        {new Date(h.created_at).toLocaleString("ru-RU", {
                          day: "2-digit",
                          month: "2-digit",
                          year: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </div>
                    </div>
                    {h.meta ? (
                      <div className="rounded-lg border border-zinc-200 bg-white px-2 py-1 text-[9px] font-black text-zinc-600 uppercase">
                        META
                      </div>
                    ) : null}
                  </div>
                </div>
              ))
            )}
            {!userHistoryLoading && (!userHistoryDetailed || userHistoryDetailed.length === 0) && (
              <div className="py-12 text-center text-[11px] font-black uppercase tracking-widest text-zinc-400">
                История пуста
              </div>
            )}
          </div>

          <div className="mt-8">
            <Button
              className="w-full h-12 rounded-2xl font-black uppercase tracking-widest text-[10px]"
              onClick={() => setHistoryModalOpen(false)}
            >
              ЗАКРЫТЬ
            </Button>
          </div>
        </div>
      </Modal>
    </AppShell>
  );
}
