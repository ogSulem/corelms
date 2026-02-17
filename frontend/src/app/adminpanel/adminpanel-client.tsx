"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/hooks/use-auth";

type Module = { id: string; title: string };

type ImportJobItem = {
  job_id: string;
  object_key?: string;
  title?: string;
  source_filename?: string;
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
type TabKey = "modules" | "analytics" | "users" | "diagnostics";

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

type AdminModuleItem = {
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

type AdminSubmoduleItem = {
  id: string;
  module_id: string;
  title: string;
  order: number;
  quiz_id: string;
};

type AdminQuestionItem = {
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

type UserItem = {
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

type UserModuleProgress = {
  module_id: string;
  title: string;
  total: number;
  passed: number;
  percent: number;
  completed: boolean;
};

type UserHistoryItem = {
  id: string;
  event_type: string;
  created_at: string;
  meta: any;
};

type UserHistoryDetailedItem = {
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

type UserDetail = {
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

  async function loadImportQueue(limit = 20) {
    try {
      setImportQueueLoading(true);
      const res = await apiFetch<{ items: any[] }>(`/admin/import-jobs?limit=${encodeURIComponent(String(limit))}` as any);
      const items = Array.isArray(res?.items) ? res.items : [];
      setImportQueue(
        items.map((x) => ({
          job_id: String((x as any)?.job_id || (x as any)?.id || ""),
          object_key: String((x as any)?.object_key || ""),
          title: String((x as any)?.title || ""),
          source_filename: String((x as any)?.source_filename || ""),
          created_at: (x as any)?.created_at ? String((x as any).created_at) : undefined,
          status: (x as any)?.status ? String((x as any).status) : undefined,
          stage: (x as any)?.stage ? String((x as any).stage) : undefined,
          detail: (x as any)?.detail ? String((x as any).detail) : undefined,
          error_code: (x as any)?.error_code ? String((x as any).error_code) : undefined,
          error_hint: (x as any)?.error_hint ? String((x as any).error_hint) : undefined,
          error_message: (x as any)?.error_message ? String((x as any).error_message) : undefined,
          error: (x as any)?.error ? String((x as any).error) : null,
        }))
      );
    } catch {
      setImportQueue([]);
    } finally {
      setImportQueueLoading(false);
    }
  }

  async function cancelImportJob(jobId: string) {
    const id = String(jobId || "").trim();
    if (!id) return;
    const ok = window.confirm(`Отменить импорт job ${id}?`);
    if (!ok) return;
    try {
      await apiFetch<any>(`/admin/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" } as any);
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: { title: "ОТМЕНА ЗАПРОШЕНА", description: `JOB: ${id}` },
        })
      );
      await loadImportQueue(50);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ ОТМЕНИТЬ JOB");
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

  const [jobPanelOpen, setJobPanelOpen] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);

  const importBatchJobIdsRef = useRef<string[]>([]);
  const importCancelRequestedRef = useRef(false);
  const importInputRef = useRef<HTMLInputElement | null>(null);

  const [clientImportStage, setClientImportStage] = useState<string>("");
  const [clientImportFileName, setClientImportFileName] = useState<string>("");

  const [regenHistory, setRegenHistory] = useState<any[]>([]);
  const [regenHistoryLoading, setRegenHistoryLoading] = useState(false);

  const [importQueue, setImportQueue] = useState<ImportJobItem[]>([]);
  const [importQueueLoading, setImportQueueLoading] = useState(false);
  const [importQueueModalOpen, setImportQueueModalOpen] = useState(false);

  const [adminModules, setAdminModules] = useState<AdminModuleItem[]>([]);
  const [adminModulesLoading, setAdminModulesLoading] = useState(false);
  const [selectedAdminModuleId, setSelectedAdminModuleId] = useState<string>("");
  const [selectedAdminModuleSubs, setSelectedAdminModuleSubs] = useState<AdminSubmoduleItem[]>([]);
  const [selectedAdminModuleSubsLoading, setSelectedAdminModuleSubsLoading] = useState(false);
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
      const terminal = st === "finished" || st === "failed" || stage === "canceled";
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

  async function loadRegenHistory() {
    try {
      setRegenHistoryLoading(true);
      const res = await apiFetch<{ items: any[] }>(`/admin/regen-jobs?limit=20`);
      setRegenHistory(Array.isArray(res?.items) ? res.items : []);
    } catch {
      setRegenHistory([]);
    } finally {
      setRegenHistoryLoading(false);
    }
  }

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
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || "НЕ УДАЛОСЬ ИЗМЕНИТЬ ВИДИМОСТЬ МОДУЛЯ");
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
    void loadRegenHistory();
    void loadImportQueue(20);
  }, [tab]);
  async function cancelCurrentJob() {
    if (!selectedJobId && importBatchJobIdsRef.current.length === 0) return;
    try {
      setCancelBusy(true);
      importCancelRequestedRef.current = true;
      setClientImportStage("canceled");

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
    } finally {
      setSelectedAdminModuleSubsLoading(false);
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

  function getDraftValue<T extends keyof AdminQuestionItem>(q: AdminQuestionItem, key: T): AdminQuestionItem[T] {
    const d = questionDraftsById[String(q.id)] || {};
    if (Object.prototype.hasOwnProperty.call(d, key)) {
      return (d as any)[key];
    }
    return q[key];
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
    const ok = window.confirm(
      "Регенерировать тесты этого модуля через AI? Старые вопросы уроков будут заменены."
    );
    if (!ok) return;
    try {
      setError(null);
      const res = await apiFetch<{ ok: boolean; job_id: string }>(
        `/admin/modules/${encodeURIComponent(selectedAdminModuleId)}/regenerate-quizzes?target_questions=5`,
        {
          method: "POST",
        }
      );
      const jid = String(res?.job_id || "");
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

      void loadRegenHistory();
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
        await loadRegenHistory();
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

        const st = String(s?.status || "");
        const terminal = st === "finished" || st === "failed" || String(s?.stage || "") === "canceled";
        if (terminal) {
          saveImportState({ terminal: true });
          void loadRegenHistory();
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
            const up = await fetch(String(presign?.upload_url || ""), {
              method: "PUT",
              body: f,
              // Do not set Content-Type explicitly: it can break some S3-compatible presigned URLs
              // (SignatureDoesNotMatch) and also triggers stricter CORS.
            });
            if (!up.ok) {
              const t = await up.text().catch(() => "");
              throw new Error(`S3 upload failed: HTTP ${up.status}${t ? ` ${t.slice(0, 200)}` : ""}`);
            }
          }

          // 3) enqueue import job
          setClientImportStage("enqueue");
          const enq = await apiFetch<{ ok: boolean; job_id: string }>(`/admin/modules/enqueue-import-zip${qs}` as any, {
            method: "POST",
            body: JSON.stringify({
              object_key: String(presign?.object_key || ""),
              title: title || null,
              source_filename: String(f?.name || ""),
            }),
          });
          res = { ok: true, job_id: String((enq as any)?.job_id || "") };
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
      void loadImportQueue(20);

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
          <div className="mt-8 space-y-6">
            <div className="grid gap-6 lg:grid-cols-12 items-start">
              <div className="lg:col-span-6 rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-8 shadow-xl">
                <div className="flex items-end justify-between gap-6">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">СИСТЕМА</div>
                    <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">СТАТУС</div>
                  </div>
                  <Button
                    variant="outline"
                    className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
                    disabled={sysLoading}
                    onClick={() => void loadSystemStatus()}
                  >
                    {sysLoading ? "..." : "ОБНОВИТЬ"}
                  </Button>
                </div>

                <div className="mt-6 grid gap-3 sm:grid-cols-2">
                  {(
                    [
                      { key: "db", label: "DB" },
                      { key: "redis", label: "REDIS" },
                      { key: "rq", label: "RQ" },
                      { key: "ollama", label: "OLLAMA" },
                      { key: "hf_router", label: "HF ROUTER" },
                      { key: "s3", label: "S3" },
                    ] as { key: string; label: string }[]
                  ).map((x) => {
                    const ok = !!(sys as any)?.[x.key]?.ok;
                    return (
                      <div key={x.key} className="rounded-2xl border border-zinc-200 bg-white p-4">
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">{x.label}</div>
                        <div
                          className={
                            "mt-2 inline-flex items-center rounded-full border px-3 py-1 text-[9px] font-black uppercase tracking-widest " +
                            (ok
                              ? "border-[#284e13]/20 bg-[#284e13]/10 text-[#284e13]"
                              : "border-rose-200 bg-rose-50 text-rose-800")
                          }
                        >
                          {ok ? "OK" : "FAIL"}
                        </div>
                        {x.key === "rq" && (sys as any)?.rq ? (
                          <div className="mt-2 text-[10px] font-bold text-zinc-600 uppercase tracking-widest">
                            workers: {Number((sys as any)?.rq?.workers || 0)} · queued: {Number((sys as any)?.rq?.queued || 0)}
                          </div>
                        ) : null}
                        {x.key === "ollama" && (sys as any)?.ollama ? (
                          <div className="mt-2 text-[10px] font-bold text-zinc-600 uppercase tracking-widest break-words">
                            {String((sys as any)?.ollama?.base_url || "")} · {String((sys as any)?.ollama?.model || "")}
                          </div>
                        ) : null}
                        {x.key === "hf_router" && (sys as any)?.hf_router ? (
                          <div className="mt-2 text-[10px] font-bold text-zinc-600 uppercase tracking-widest break-words">
                            {String((sys as any)?.hf_router?.base_url || "")} · {String((sys as any)?.hf_router?.model || "")}
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="lg:col-span-6 rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-8 shadow-xl">
                <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">НЕЙРОСЕТЬ</div>
                <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">НАСТРОЙКИ</div>

                <div className="mt-6 grid gap-4">
                  <label className="flex items-center justify-between gap-4 rounded-2xl border border-zinc-200 bg-white px-5 py-4">
                    <div>
                      <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">LLM PROVIDER ORDER</div>
                      <div className="mt-1 text-[11px] font-bold text-zinc-700">например: ollama,hf_router</div>
                    </div>
                    <input
                      value={llmOrderDraft}
                      onChange={(e) => setLlmOrderDraft(e.target.value)}
                      placeholder="ollama,hf_router"
                      className="w-[240px] h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
                    />
                  </label>

                  <div className="grid gap-3 rounded-2xl border border-zinc-200 bg-white p-5">
                    <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">OLLAMA</div>
                    <label className="flex items-center justify-between gap-4">
                      <div className="text-[11px] font-bold text-zinc-800">ВКЛЮЧЕНО</div>
                      <input
                        type="checkbox"
                        checked={ollamaEnabledDraft}
                        onChange={(e) => setOllamaEnabledDraft(e.target.checked)}
                        className="h-5 w-5"
                      />
                    </label>
                    <div className="grid gap-2">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">BASE URL</div>
                      <input
                        value={ollamaBaseUrlDraft}
                        onChange={(e) => setOllamaBaseUrlDraft(e.target.value)}
                        placeholder="http://host.docker.internal:11434"
                        className="h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
                      />
                      {llmEffective?.ollama_base_url ? (
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">
                          EFFECTIVE: {String(llmEffective.ollama_base_url)}
                        </div>
                      ) : null}
                    </div>
                    <div className="grid gap-2">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">MODEL</div>
                      <input
                        value={ollamaModelDraft}
                        onChange={(e) => setOllamaModelDraft(e.target.value)}
                        placeholder="gemma3:4b"
                        className="h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
                      />
                      {llmEffective?.ollama_model ? (
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">
                          EFFECTIVE: {String(llmEffective.ollama_model)}
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div className="grid gap-3 rounded-2xl border border-zinc-200 bg-white p-5">
                    <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">HF ROUTER</div>
                    <label className="flex items-center justify-between gap-4">
                      <div className="text-[11px] font-bold text-zinc-800">ВКЛЮЧЕНО</div>
                      <input
                        type="checkbox"
                        checked={hfEnabledDraft}
                        onChange={(e) => setHfEnabledDraft(e.target.checked)}
                        className="h-5 w-5"
                      />
                    </label>
                    <div className="grid gap-2">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">BASE URL</div>
                      <input
                        value={hfBaseUrlDraft}
                        onChange={(e) => setHfBaseUrlDraft(e.target.value)}
                        placeholder="https://router.huggingface.co/v1"
                        className="h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
                      />
                      {llmEffective?.hf_router_base_url ? (
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">
                          EFFECTIVE: {String(llmEffective.hf_router_base_url)}
                        </div>
                      ) : null}
                    </div>
                    <div className="grid gap-2">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">MODEL</div>
                      <input
                        value={hfModelDraft}
                        onChange={(e) => setHfModelDraft(e.target.value)}
                        placeholder="deepseek-ai/DeepSeek-R1:novita"
                        className="h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
                      />
                      {llmEffective?.hf_router_model ? (
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">
                          EFFECTIVE: {String(llmEffective.hf_router_model)}
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">HF TOKEN</div>
                    <input
                      value={hfTokenDraft}
                      onChange={(e) => setHfTokenDraft(e.target.value)}
                      placeholder="hf_..."
                      className="mt-2 w-full h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
                    />
                    <div className="mt-2 text-[9px] font-black uppercase tracking-widest text-zinc-500">
                      хранится в Redis (runtime), не в .env{hfTokenMasked ? ` · СЕЙЧАС: ${hfTokenMasked}` : ""}
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <Button
                        variant="outline"
                        className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
                        disabled={diagSaving}
                        onClick={() => void clearRuntimeHfToken()}
                      >
                        ОЧИСТИТЬ TOKEN
                      </Button>
                    </div>
                  </div>

                  <Button
                    variant="primary"
                    className="h-11 rounded-2xl font-black uppercase tracking-widest text-[9px]"
                    disabled={diagSaving}
                    onClick={() => void saveRuntimeLlmSettings()}
                  >
                    {diagSaving ? "..." : "СОХРАНИТЬ"}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {tab === "modules" ? (
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
                        disabled={importLockedInfo.locked}
                      />
                      <button
                        type="button"
                        className="h-8 rounded-xl border border-zinc-200 bg-white px-3 text-[9px] font-black uppercase tracking-widest text-zinc-800 hover:bg-zinc-50"
                        disabled={importLockedInfo.locked}
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
                      disabled={
                        importLockedInfo.locked || importFiles.length === 0
                      }
                      onClick={() => void startImport()}
                    >
                      {importBusy ? "..." : "ЗАПУСТИТЬ"}
                    </Button>
                  </div>
                </div>

                {importLockedInfo.locked ? (
                  <div className="mt-3 rounded-2xl border border-[#fe9900]/25 bg-[#fe9900]/10 px-4 py-3 text-[10px] font-black uppercase tracking-widest text-zinc-900">
                    ИМПОРТ НЕДОСТУПЕН: {importLockedInfo.reason}
                  </div>
                ) : null}

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
                        onClick={() => void loadImportQueue(20)}
                        disabled={importQueueLoading}
                      >
                        {importQueueLoading ? "..." : "ОБНОВИТЬ"}
                      </button>
                      <button
                        type="button"
                        className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                        onClick={() => setImportQueueModalOpen(true)}
                        disabled={!importQueue.length}
                      >
                        ВСЯ ОЧЕРЕДЬ
                      </button>
                    </div>
                  </div>

                  <div className="mt-3 grid gap-2">
                    {(importQueue || []).slice(0, 3).map((it) => {
                      const st = String(it.status || "").toLowerCase();
                      const stage = String(it.stage || "").toLowerCase();
                      const terminal = st === "finished" || st === "failed" || stage === "canceled";
                      return (
                        <div key={it.job_id} className="flex items-center justify-between gap-3 rounded-xl border border-zinc-200 bg-white px-3 py-2">
                          <div className="min-w-0">
                            <div className="truncate text-[10px] font-black uppercase tracking-widest text-zinc-900">
                              {(it.title || it.source_filename || it.object_key || "ZIP").toString()}
                            </div>
                            <div className="mt-1 flex flex-wrap items-center gap-2">
                              <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                {(it.status || "—").toString().toUpperCase()}
                              </div>
                              <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                {(it.stage || "—").toString().toUpperCase()}
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
                        ВСЕ ЗАДАЧИ
                        <span className="ml-2 text-zinc-400">{importQueueLoading ? "..." : importQueue.length}</span>
                      </div>
                      <Button variant="outline" className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]" onClick={() => void loadImportQueue(50)}>
                        ОБНОВИТЬ
                      </Button>
                    </div>

                    <div className="max-h-[520px] overflow-auto pr-1 grid gap-2">
                      {(importQueue || []).map((it) => {
                        const st = String(it.status || "").toLowerCase();
                        const stage = String(it.stage || "").toLowerCase();
                        const terminal = st === "finished" || st === "failed" || stage === "canceled";
                        const label = (it.title || it.source_filename || it.object_key || "ZIP").toString();
                        return (
                          <div key={it.job_id} className="rounded-xl border border-zinc-200 bg-white p-3">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="truncate text-[10px] font-black uppercase tracking-widest text-zinc-900">{label}</div>
                                <div className="mt-2 flex flex-wrap items-center gap-2">
                                  <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                    {(it.status || "—").toString().toUpperCase()}
                                  </div>
                                  <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                    {(it.stage || "—").toString().toUpperCase()}
                                  </div>
                                  <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                    {String(it.job_id || "").slice(0, 10)}
                                  </div>
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

                {jobPanelOpen ? (
                  <div className="mt-3 rounded-2xl border border-zinc-200 bg-white p-3">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ЗАДАЧА</div>
                        <div className="mt-1 truncate text-[11px] font-black text-zinc-950">{selectedJobId || "—"}</div>
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
                          disabled={!selectedJobId || cancelBusy || ["finished", "failed"].includes(String(jobStatus || ""))}
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

                    {clientImportStage ? (
                      <div className="mt-3 text-[10px] font-black uppercase tracking-widest text-zinc-600">
                        CLIENT: {clientImportStage.toUpperCase()} {clientImportFileName ? `· ${clientImportFileName}` : ""}
                        {importBatch ? ` · ${importBatch.done}/${importBatch.total}` : ""}
                      </div>
                    ) : null}

                    {selectedAdminModule ? (
                      <div className="mt-4 flex flex-wrap items-center gap-2">
                        <div className="rounded-full border border-zinc-200 bg-white px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                          AI {selectedAdminModuleQuality.ai_current}
                        </div>
                        <div className="rounded-full border border-zinc-200 bg-white px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                          HEUR {selectedAdminModuleQuality.heur_current}
                        </div>
                        <div className="rounded-full border border-zinc-200 bg-white px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                          TOTAL {selectedAdminModuleQuality.total_current}
                        </div>
                        <div
                          className={
                            "rounded-full border px-3 py-1 text-[9px] font-black uppercase tracking-widest " +
                            (selectedAdminModuleQuality.fallback_current > 0
                              ? "border-[#fe9900]/25 bg-[#fe9900]/10 text-[#fe9900]"
                              : "border-zinc-200 bg-white text-zinc-700")
                          }
                        >
                          FALLBACK {selectedAdminModuleQuality.fallback_current}
                        </div>
                        <div
                          className={
                            "rounded-full border px-3 py-1 text-[9px] font-black uppercase tracking-widest " +
                            (selectedAdminModuleQuality.needs_regen_current > 0
                              ? "border-[#fe9900]/25 bg-[#fe9900]/10 text-[#fe9900]"
                              : "border-[#284e13]/20 bg-[#284e13]/10 text-[#284e13]")
                          }
                        >
                          NEEDS {selectedAdminModuleQuality.needs_regen_current}
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>

              <div className="lg:col-span-5">
                {jobPanelOpen ? (
                  <div className="relative overflow-hidden rounded-[22px] border border-zinc-200 bg-white/70 backdrop-blur-md p-3 shadow-2xl shadow-zinc-950/10">
                    <div className="rounded-2xl border border-zinc-200 bg-white p-3">
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0">
                          <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">РЕЗУЛЬТАТ</div>
                          <div className="mt-1 truncate text-[11px] font-black text-zinc-950">{selectedJobId || "—"}</div>
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                              {(jobStatus || "—").toUpperCase()}
                            </div>
                            <div className="rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                              {(importJobStageLabel || jobStage || "—").toString()}
                            </div>
                          </div>
                        </div>
                      </div>

                      {jobStatus === "finished" && jobResult && typeof jobResult === "object" ? (
                        <div className="mt-3 rounded-2xl border border-zinc-200 bg-white p-4">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">СВОДКА</div>
                            {typeof (jobResult as any)?.report?.needs_regen_db !== "undefined" ? (
                              <div
                                className={
                                  "rounded-full border px-3 py-1 text-[9px] font-black uppercase tracking-widest " +
                                  (Number((jobResult as any)?.report?.needs_regen_db || 0) > 0
                                    ? "border-[#fe9900]/30 bg-[#fe9900]/10 text-zinc-900"
                                    : "border-[#284e13]/20 bg-[#284e13]/10 text-[#284e13]")
                                }
                              >
                                ТРЕБУЕТ ДОРАБОТКИ: {Number((jobResult as any)?.report?.needs_regen_db || 0)}
                              </div>
                            ) : null}
                          </div>
                          {(jobResult as any)?.report && typeof (jobResult as any)?.report === "object" ? (
                            <div className="mt-3 grid gap-3 sm:grid-cols-2">
                              <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ВОПРОСЫ</div>
                                <div className="mt-2 text-[11px] font-bold text-zinc-900">
                                  ВСЕГО: {Number(((jobResult as any)?.report as any)?.questions_total || 0)} · AI: {Number(((jobResult as any)?.report as any)?.questions_ai || 0)} · ФОЛБЭК: {Number(((jobResult as any)?.report as any)?.questions_fallback || 0)}
                                </div>
                              </div>
                              <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">AI</div>
                                <div className="mt-2 text-[11px] font-bold text-zinc-900">
                                  СБОЕВ: {Number(((jobResult as any)?.report as any)?.ollama_failures || 0)} · УРОКОВ: {Number(((jobResult as any)?.report as any)?.submodules || 0)}
                                </div>
                              </div>
                            </div>
                          ) : null}
                          <div className="mt-3 overflow-hidden rounded-xl border border-zinc-100 bg-white/50 p-3">
                            <pre className="text-[9px] font-mono text-zinc-600 whitespace-pre-wrap break-words overflow-x-hidden max-h-[320px] overflow-y-auto">
                              {JSON.stringify(jobResult, null, 2)}
                            </pre>
                          </div>
                        </div>
                      ) : (
                        <div className="mt-3 rounded-2xl border border-zinc-200 bg-white p-4">
                          <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">RESULT</div>
                          <div className="mt-2 text-[11px] font-bold text-zinc-500">—</div>
                        </div>
                      )}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>

            <div className="grid gap-6 lg:grid-cols-12 items-start">
              <div className="lg:col-span-4 relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-6 shadow-2xl shadow-zinc-950/10">
                <div className="flex items-end justify-between gap-6">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">МОДУЛИ</div>
                    <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">СПИСОК</div>
                  </div>
                  <Button
                    variant="ghost"
                    className="h-12 rounded-2xl font-black uppercase tracking-widest text-[9px]"
                    disabled={adminModulesLoading}
                    onClick={() => void loadAdminModules()}
                  >
                    {adminModulesLoading ? "..." : "ОБНОВИТЬ"}
                  </Button>
                </div>

                <div className="mt-5 grid gap-2 max-h-[520px] overflow-auto pr-1">
                  {(adminModules || []).map((m) => {
                    const active = String(m.id) === String(selectedAdminModuleId);
                    const q = (m as any).question_quality as
                      | {
                          total_current: number;
                          needs_regen_current: number;
                          fallback_current: number;
                          ai_current: number;
                          heur_current: number;
                        }
                      | undefined;
                    return (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => setSelectedAdminModuleId(String(m.id))}
                        className={
                          "w-full text-left rounded-2xl border px-4 py-3 transition " +
                          (active ? "border-[#fe9900]/25 bg-[#fe9900]/10" : "border-zinc-200 bg-white hover:bg-zinc-50")
                        }
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-[11px] font-black uppercase tracking-widest text-zinc-950">
                              {m.title}
                            </div>
                            <div className="mt-1 text-[9px] font-black uppercase tracking-widest text-zinc-600">
                              {m.is_active ? "АКТИВЕН" : "НЕОБХОДИМ РЕГЕН (СКРЫТ ДО ГОТОВНОСТИ)"}
                            </div>
                            {q ? (
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                <div className="rounded-full border border-zinc-200 bg-white px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                  AI {Number(q.ai_current || 0)}
                                </div>
                                <div className="rounded-full border border-zinc-200 bg-white px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                  HEUR {Number(q.heur_current || 0)}
                                </div>
                                <div className="rounded-full border border-zinc-200 bg-white px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                  TOTAL {Number(q.total_current || 0)}
                                </div>
                                <div
                                  className={
                                    "rounded-full border px-2 py-0.5 text-[9px] font-black uppercase tracking-widest " +
                                    (Number(q.fallback_current || 0) > 0
                                      ? "border-[#fe9900]/25 bg-[#fe9900]/10 text-[#fe9900]"
                                      : "border-zinc-200 bg-white text-zinc-700")
                                  }
                                >
                                  FALLBACK {Number(q.fallback_current || 0)}
                                </div>
                                <div
                                  className={
                                    "rounded-full border px-2 py-0.5 text-[9px] font-black uppercase tracking-widest " +
                                    (Number(q.needs_regen_current || 0) > 0
                                      ? "border-[#fe9900]/25 bg-[#fe9900]/10 text-[#fe9900]"
                                      : "border-[#284e13]/20 bg-[#284e13]/10 text-[#284e13]")
                                  }
                                >
                                  NEEDS {Number(q.needs_regen_current || 0)}
                                </div>
                              </div>
                            ) : null}
                          </div>
                          <div
                            className={
                              "shrink-0 rounded-full px-3 py-1 text-[9px] font-black uppercase tracking-widest border " +
                              (m.is_active
                                ? "border-[#284e13]/20 bg-[#284e13]/10 text-[#284e13]"
                                : "border-[#fe9900]/25 bg-[#fe9900]/10 text-[#fe9900]")
                            }
                          >
                            {m.is_active ? "АКТИВЕН" : "РЕГЕН"}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="lg:col-span-8 relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-10 shadow-2xl shadow-zinc-950/10">
                <div className="flex flex-wrap items-start justify-between gap-6">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900] mb-2">КАРТОЧКА</div>
                    <div className="text-2xl font-black tracking-tighter text-zinc-950 uppercase leading-none">
                      {selectedAdminModule ? selectedAdminModule.title : selectedAdminModuleId ? "ЗАГРУЗКА..." : "ВЫБЕРИТЕ МОДУЛЬ"}
                    </div>
                    {selectedAdminModule ? (
                      <div className="mt-3 flex flex-wrap items-center gap-3">
                        <div className="text-sm text-zinc-500 font-bold uppercase tracking-widest">
                          {selectedAdminModule.is_active ? "ВИДИМ СОТРУДНИКАМ" : "СКРЫТ"}
                        </div>
                        <Button
                          variant={selectedAdminModule.is_active ? "outline" : "primary"}
                          className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                          onClick={() => void setSelectedModuleVisibility(!selectedAdminModule.is_active)}
                        >
                          {selectedAdminModule.is_active ? "СКРЫТЬ" : "ПОКАЗАТЬ"}
                        </Button>
                      </div>
                    ) : null}
                  </div>

                  <div className="shrink-0 flex flex-col gap-2">
                    <Button
                      variant="primary"
                      className="h-11 rounded-xl shadow-xl shadow-[#fe9900]/20"
                      disabled={!selectedAdminModuleId || !!activeRegenByModuleId[String(selectedAdminModuleId || "")]}
                      onClick={() => void regenerateSelectedModuleQuizzes()}
                    >
                      {activeRegenByModuleId[String(selectedAdminModuleId || "")]
                        ? "РЕГЕН ЗАПУЩЕН"
                        : "РЕГЕН ТЕСТОВ"}
                    </Button>
                    <Button
                      variant="destructive"
                      className="h-11 rounded-xl font-black uppercase tracking-widest text-[9px]"
                      disabled={!selectedAdminModuleId}
                      onClick={() => void deleteSelectedModule()}
                    >
                      УДАЛИТЬ
                    </Button>
                  </div>
                </div>

                <div className="mt-8 grid gap-4">
                  <div className="rounded-2xl border border-zinc-200 bg-white p-6">
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Уроки</div>
                        <div className="mt-2 text-lg font-black text-zinc-950 uppercase">Подмодули</div>
                      </div>
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-600">
                        {selectedAdminModuleSubs.length}
                      </div>
                    </div>

                    <div className="mt-5">
                      {selectedAdminModuleSubsLoading ? (
                        <div className="py-10 text-center text-[10px] font-black uppercase tracking-widest text-zinc-600">
                          Загрузка...
                        </div>
                      ) : selectedAdminModuleSubs.length === 0 ? (
                        <div className="py-10 text-center text-[10px] font-black uppercase tracking-widest text-zinc-600">
                          {selectedAdminModuleId ? "Нет уроков" : "Выберите модуль"}
                        </div>
                      ) : (
                        <div className="grid gap-2 sm:grid-cols-2">
                          {selectedAdminModuleSubs.map((s) => {
                            const active = String(s.id) === String(selectedSubmoduleId);
                            return (
                              <button
                                key={s.id}
                                type="button"
                                onClick={() => {
                                  setSelectedSubmoduleId(String(s.id));
                                  setSelectedQuizId(String(s.quiz_id || ""));
                                }}
                                className={
                                  "w-full text-left rounded-2xl border p-4 transition " +
                                  (active
                                    ? "border-[#fe9900]/25 bg-[#fe9900]/10"
                                    : "border-zinc-200 bg-white hover:bg-zinc-50")
                                }
                              >
                                <div className="truncate text-[11px] font-black uppercase tracking-widest text-zinc-950">{s.title}</div>
                                <div className="mt-2 text-[9px] font-black uppercase tracking-widest text-zinc-600 break-all">
                                  QUIZ: {String(s.quiz_id || "—")}
                                </div>
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="rounded-2xl border border-zinc-200 bg-white p-6">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div>
                        <div className="text-[9px] font-black uppercase tracking-[0.3em] text-[#fe9900]">Квизы и вопросы</div>
                        <div className="mt-2 text-sm font-bold text-zinc-600">
                          Выбери урок сверху — ниже появятся вопросы. Финальный тест для сотрудников собирается автоматически.
                        </div>
                      </div>
                      <div className="shrink-0 flex flex-wrap items-center gap-2">
                        <Button
                          variant="primary"
                          className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
                          disabled={!selectedQuizId || newQuestionBusy}
                          onClick={() => void createQuestionAdmin(selectedQuizId)}
                        >
                          {newQuestionBusy ? "..." : "ДОБАВИТЬ ВОПРОС"}
                        </Button>
                        <Button
                          variant="outline"
                          className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
                          disabled={!selectedQuizId || questionsLoadingQuizId === String(selectedQuizId || "")}
                          onClick={() => void loadQuestionsForQuiz(selectedQuizId)}
                        >
                          {questionsLoadingQuizId === String(selectedQuizId || "") ? "..." : "ОБНОВИТЬ"}
                        </Button>
                      </div>
                    </div>

                    <div className="mt-5">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Вопросы</div>
                      {!selectedQuizId ? (
                        <div className="mt-4 rounded-2xl border border-zinc-200 bg-zinc-50 p-4 text-[10px] font-black uppercase tracking-widest text-zinc-600">
                          Выбери урок или финальный тест выше
                        </div>
                      ) : questionsLoadingQuizId === String(selectedQuizId || "") && !selectedQuizQuestions.length ? (
                        <div className="mt-4 rounded-2xl border border-zinc-200 bg-zinc-50 p-4 text-[10px] font-black uppercase tracking-widest text-zinc-600">
                          Загрузка...
                        </div>
                      ) : selectedQuizQuestions.length === 0 ? (
                        <div className="mt-4 rounded-2xl border border-zinc-200 bg-zinc-50 p-4 text-[10px] font-black uppercase tracking-widest text-zinc-600">
                          Вопросов нет
                        </div>
                      ) : (
                        <div className="mt-4 grid gap-3">
                          {selectedQuizQuestions.map((q, idx) => (
                              <div key={String(q.id)} className="rounded-2xl border border-zinc-200 bg-white p-4">
                                <div className="flex items-start justify-between gap-4">
                                  <div className="min-w-0">
                                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ВОПРОС {idx + 1}</div>
                                    <div className="mt-1 text-[10px] font-black text-zinc-950 break-words max-w-full truncate">{String(q.id)}</div>
                                    <div className="mt-2 flex flex-wrap items-center gap-2">
                                      {isQuestionDirty(q) ? (
                                        <div className="rounded-full border border-[#fe9900]/25 bg-[#fe9900]/10 px-2.5 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-900">
                                          ИЗМЕНЕНО
                                        </div>
                                      ) : (
                                        <div className="rounded-full border border-[#284e13]/20 bg-[#284e13]/10 px-2.5 py-1 text-[9px] font-black uppercase tracking-widest text-[#284e13]">
                                          СОХРАНЕНО
                                        </div>
                                      )}
                                      {questionSavingId === String(q.id) ? (
                                        <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-600">
                                          СЕЙВ...
                                        </div>
                                      ) : null}
                                    </div>
                                  </div>
                                  <div className="shrink-0 flex items-center gap-2">
                                    <button
                                      type="button"
                                      className="rounded-xl border border-[#284e13]/20 bg-[#284e13]/10 px-3 py-2 text-[9px] font-black uppercase tracking-widest text-[#284e13] hover:bg-[#284e13]/15 disabled:opacity-50"
                                      disabled={!isQuestionDirty(q) || questionSavingId === String(q.id)}
                                      onClick={() => void saveQuestionDraft(String(q.id))}
                                    >
                                      СОХРАНИТЬ
                                    </button>
                                    <button
                                      type="button"
                                      className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                                      onClick={() => void copy(String(q.id))}
                                    >
                                      COPY
                                    </button>
                                    <button
                                      type="button"
                                      className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[9px] font-black uppercase tracking-widest text-rose-800 hover:bg-rose-100"
                                      onClick={() => void deleteQuestionAdmin(String(q.id))}
                                    >
                                      УДАЛИТЬ
                                    </button>
                                  </div>
                                </div>

                                <div className="mt-4">
                                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500 ml-1">PROMPT</div>
                                  <textarea
                                    className="mt-2 w-full min-h-[90px] rounded-xl bg-white border border-zinc-200 px-4 py-3 text-[12px] font-bold text-zinc-950 outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
                                    value={String(getDraftValue(q, "prompt") || "")}
                                    disabled={questionSavingId === String(q.id)}
                                    onChange={(e) => {
                                      const v = e.target.value;
                                      setQuestionDraftsById((prev) => ({
                                        ...prev,
                                        [String(q.id)]: { ...(prev[String(q.id)] || {}), prompt: v },
                                      }));
                                    }}
                                  />
                                </div>

                                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                                  <div>
                                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500 ml-1">CORRECT_ANSWER</div>
                                    <textarea
                                      className="mt-2 w-full min-h-[70px] rounded-xl bg-white border border-zinc-200 px-4 py-3 text-[12px] font-bold text-zinc-950 outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
                                      value={String(getDraftValue(q, "correct_answer") || "")}
                                      disabled={questionSavingId === String(q.id)}
                                      onChange={(e) => {
                                        const v = e.target.value;
                                        setQuestionDraftsById((prev) => ({
                                          ...prev,
                                          [String(q.id)]: { ...(prev[String(q.id)] || {}), correct_answer: v },
                                        }));
                                      }}
                                    />
                                    <div className="mt-2 text-[9px] font-black uppercase tracking-widest text-zinc-500">
                                      ФОРМАТ: A / b / ABCD / A,B,C (ЛЮБОЙ)
                                    </div>
                                  </div>
                                  <div>
                                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500 ml-1">EXPLANATION</div>
                                    <textarea
                                      className="mt-2 w-full min-h-[70px] rounded-xl bg-white border border-zinc-200 px-4 py-3 text-[12px] font-bold text-zinc-950 outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
                                      value={String(getDraftValue(q, "explanation") || "")}
                                      disabled={questionSavingId === String(q.id)}
                                      onChange={(e) => {
                                        const v = e.target.value;
                                        setQuestionDraftsById((prev) => ({
                                          ...prev,
                                          [String(q.id)]: { ...(prev[String(q.id)] || {}), explanation: v },
                                        }));
                                      }}
                                    />
                                  </div>
                                </div>

                                <div className="mt-4">
                                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500 ml-1">CONCEPT_TAG</div>
                                  <input
                                    className="mt-2 h-11 w-full rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
                                    value={String(getDraftValue(q, "concept_tag") || "")}
                                    disabled={questionSavingId === String(q.id)}
                                    onChange={(e) => {
                                      const v = e.target.value;
                                      setQuestionDraftsById((prev) => ({
                                        ...prev,
                                        [String(q.id)]: { ...(prev[String(q.id)] || {}), concept_tag: v },
                                      }));
                                    }}
                                    placeholder="(опционально)"
                                  />
                                </div>
                              </div>
                            ))}
                          </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : tab === "users" ? (
          <div className="mt-8 space-y-6">
            <div className="grid gap-6 lg:grid-cols-12 items-start">
              <div className="lg:col-span-8 relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-6 shadow-2xl shadow-zinc-950/10">
                <div className="flex items-end justify-between gap-6">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900]">Пользователи</div>
                    <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">Быстрая выдача доступа</div>
                  </div>
                  <Button
                    className="h-12 rounded-2xl font-black uppercase tracking-widest text-[9px]"
                    disabled={newUserBusy}
                    onClick={createUser}
                  >
                    {newUserBusy ? "СОЗДАНИЕ..." : "СОЗДАТЬ"}
                  </Button>
                </div>

                <div className="mt-6 grid gap-4 lg:grid-cols-12 items-end">
                  <div className="lg:col-span-4">
                    <div className="text-[9px] font-black text-zinc-600 uppercase tracking-widest ml-1">Имя</div>
                    <input
                      className="mt-2 w-full h-12 rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
                      value={newUserName}
                      onChange={(e) => setNewUserName(e.target.value)}
                      placeholder="Например: Иван Петров"
                    />
                  </div>
                  <div className="lg:col-span-4">
                    <div className="text-[9px] font-black text-zinc-600 uppercase tracking-widest ml-1">Должность</div>
                    <input
                      className="mt-2 w-full h-12 rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
                      value={newUserPosition}
                      onChange={(e) => setNewUserPosition(e.target.value)}
                      placeholder="Например: Менеджер"
                    />
                  </div>
                  <div className="lg:col-span-2">
                    <div className="text-[9px] font-black text-zinc-600 uppercase tracking-widest ml-1">Роль</div>
                    <select
                      className="mt-2 w-full h-12 rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all appearance-none cursor-pointer"
                      value={newUserRole}
                      onChange={(e) => setNewUserRole(e.target.value as any)}
                    >
                      <option value="employee">СОТРУДНИК</option>
                      <option value="admin">АДМИН</option>
                    </select>
                  </div>
                  <div className="lg:col-span-2 flex items-center justify-end">
                    <Button
                      variant="ghost"
                      className="h-12 w-full rounded-xl font-black uppercase tracking-widest text-[9px]"
                      disabled={usersLoading}
                      onClick={() => void loadUsers()}
                    >
                      {usersLoading ? "ОБНОВЛЕНИЕ..." : "ОБНОВИТЬ"}
                    </Button>
                  </div>
                </div>

                {newUserTempPassword ? (
                  <div className="mt-4 rounded-2xl border border-zinc-200 bg-white p-4">
                    <div className="flex items-center justify-between gap-4">
                      <div className="text-[9px] font-black uppercase tracking-widest text-[#fe9900]">Временный пароль</div>
                      <button
                        className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                        onClick={() => void copy(newUserTempPassword)}
                        type="button"
                      >
                        КОПИРОВАТЬ
                      </button>
                    </div>
                    <div className="mt-2 text-sm font-black text-zinc-950 break-all">{newUserTempPassword}</div>
                  </div>
                ) : null}
              </div>

              <div className="lg:col-span-4 relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-6 shadow-2xl shadow-zinc-950/10">
                <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Подсказка</div>
                <div className="mt-2 text-sm font-bold text-zinc-600">
                  Админ видит всё. Сотруднику доступен только контент. После входа пользователь должен сменить временный пароль.
                </div>
              </div>
            </div>

            <div className="grid gap-6 lg:grid-cols-12 items-start">
              <div className="lg:col-span-5 relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-6 shadow-2xl shadow-zinc-950/10">
                <div className="flex items-center justify-between gap-4">
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Сотрудники</div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600">{users.length}</div>
                </div>

                <div className="mt-4">
                  <input
                    className="w-full h-11 rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
                    value={userQuery}
                    onChange={(e) => setUserQuery(e.target.value)}
                    placeholder="ПОИСК ПО ИМЕНИ"
                  />
                </div>

                <div className="mt-4 space-y-2 max-h-[520px] overflow-auto pr-1">
                  {(users || [])
                    .filter((u) => {
                      const q = (userQuery || "").trim().toLowerCase();
                      if (!q) return true;
                      return String(u.name || "").toLowerCase().includes(q);
                    })
                    .map((u) => {
                      const active = String(u.id) === String(selectedUserId);
                      return (
                        <button
                          key={u.id}
                          type="button"
                          onClick={() => setSelectedUserId(String(u.id))}
                          className={
                            "w-full text-left rounded-2xl border px-4 py-3 transition " +
                            (active ? "border-[#fe9900]/25 bg-[#fe9900]/10" : "border-zinc-200 bg-white hover:bg-zinc-50")
                          }
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="truncate text-[11px] font-black uppercase tracking-widest text-zinc-950">{u.name}</div>
                              <div className="mt-1 truncate text-[10px] font-black uppercase tracking-widest text-zinc-600">
                                {u.position ? u.position : u.role}
                              </div>
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                  ГОТОВО {Number(u.progress_summary?.completed_count || 0)}
                                </div>
                                <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                  В РАБОТЕ {Number(u.progress_summary?.in_progress_count || 0)}
                                </div>
                                {u.progress_summary?.current ? (
                                  <div className="min-w-0 rounded-full border border-[#fe9900]/25 bg-[#fe9900]/10 px-2.5 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-900">
                                    <span className="truncate">{String(u.progress_summary.current.title || "").toUpperCase()}</span>
                                    <span className="ml-2 tabular-nums">{Number(u.progress_summary.current.percent || 0)}%</span>
                                  </div>
                                ) : null}
                              </div>
                            </div>
                            <div className="shrink-0 text-[9px] font-black uppercase tracking-widest text-zinc-500">{u.role}</div>
                          </div>
                        </button>
                      );
                    })}
                </div>
              </div>
 
              <div className="lg:col-span-7 space-y-6">
                <div className="relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-10 shadow-2xl shadow-zinc-950/10">
                  <div className="flex items-start justify-between gap-6">
                    <div>
                      <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900] mb-2">Карточка</div>
                      <div className="text-2xl font-black tracking-tighter text-zinc-950 uppercase leading-none">
                        {userDetail ? userDetail.name : selectedUserId ? "Загрузка..." : "Выберите сотрудника"}
                      </div>
                      {userDetail?.position ? (
                        <div className="mt-3 text-sm text-zinc-500 font-bold uppercase tracking-widest">{userDetail.position}</div>
                      ) : null}
                    </div>

                    <div className="shrink-0 flex flex-col gap-2">
                      <Button
                        variant="ghost"
                        className="h-11 rounded-xl font-black uppercase tracking-widest text-[9px]"
                        disabled={!selectedUserId || resetBusy}
                        onClick={resetPassword}
                      >
                        {resetBusy ? "СБРОС..." : "СБРОСИТЬ ПАРОЛЬ"}
                      </Button>
                      <Button
                        variant="destructive"
                        className="h-11 rounded-xl font-black uppercase tracking-widest text-[9px]"
                        disabled={!selectedUserId || deleteUserBusy}
                        onClick={deleteSelectedUser}
                      >
                        {deleteUserBusy ? "УДАЛЕНИЕ..." : "УДАЛИТЬ"}
                      </Button>
                    </div>
                  </div>

                  {userDetailLoading ? (
                    <div className="mt-8 flex items-center justify-center py-10">
                      <div className="h-12 w-12 rounded-full border-2 border-[#fe9900]/30 border-t-[#fe9900] animate-spin" />
                    </div>
                  ) : userDetail ? (
                    <div className="mt-8 grid gap-4">
                      <div className="grid gap-3 sm:grid-cols-3">
                        <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                          <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">XP</div>
                          <div className="mt-2 text-2xl font-black tabular-nums text-zinc-950">{String(userDetail.xp ?? 0)}</div>
                        </div>
                        <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                          <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">УРОВЕНЬ</div>
                          <div className="mt-2 text-2xl font-black tabular-nums text-zinc-950">{String(userDetail.level ?? 0)}</div>
                        </div>
                        <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                          <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">СЕРИЯ</div>
                          <div className="mt-2 text-2xl font-black tabular-nums text-zinc-950">{String(userDetail.streak ?? 0)}</div>
                        </div>
                      </div>

                      <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                        <div className="flex flex-wrap items-center justify-between gap-4">
                          <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Статус</div>
                          <div
                            className={
                              "rounded-full px-3 py-1 text-[9px] font-black uppercase tracking-widest border " +
                              (userDetail.must_change_password
                                ? "border-rose-500/20 bg-rose-500/10 text-rose-700"
                                : "border-[#284e13]/20 bg-[#284e13]/10 text-[#284e13]")
                            }
                          >
                            {userDetail.must_change_password ? "ТРЕБУЕТ СМЕНЫ ПАРОЛЯ" : "ПАРОЛЬ АКТУАЛЕН"}
                          </div>
                        </div>
                        <div className="mt-4 grid gap-3 sm:grid-cols-5">
                          <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3">
                            <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Назнач.</div>
                            <div className="mt-2 text-lg font-black tabular-nums text-zinc-950">{String(userDetail.stats.assignments_total)}</div>
                          </div>
                          <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3">
                            <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Выполн.</div>
                            <div className="mt-2 text-lg font-black tabular-nums text-zinc-950">{String(userDetail.stats.assignments_completed)}</div>
                          </div>
                          <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3">
                            <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Попыток</div>
                            <div className="mt-2 text-lg font-black tabular-nums text-zinc-950">{String(userDetail.stats.attempts_total)}</div>
                          </div>
                          <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3">
                            <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Сдал</div>
                            <div className="mt-2 text-lg font-black tabular-nums text-zinc-950">{String(userDetail.stats.attempts_passed)}</div>
                          </div>
                          <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3">
                            <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Событий</div>
                            <div className="mt-2 text-lg font-black tabular-nums text-zinc-950">{String(userDetail.stats.events_total)}</div>
                          </div>
                        </div>

                        {/* Модули в процессе и завершенные */}
                        <div className="mt-6 grid gap-6 sm:grid-cols-2">
                          <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                            <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500 mb-4">В процессе</div>
                            {userDetail.modules_progress.in_progress.length > 0 ? (
                              <div className="space-y-3">
                                {userDetail.modules_progress.in_progress.map((m) => (
                                  <div key={m.module_id} className="space-y-2">
                                    <div className="flex items-center justify-between gap-4">
                                      <div className="text-[11px] font-black text-zinc-950 truncate">{m.title}</div>
                                      <div className="text-[10px] font-black text-[#fe9900] tabular-nums">{m.percent}%</div>
                                    </div>
                                    <div className="h-1.5 w-full rounded-full bg-zinc-100 overflow-hidden">
                                      <div 
                                        className="h-full bg-[#fe9900] transition-all duration-500" 
                                        style={{ width: `${m.percent}%` }}
                                      />
                                    </div>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest">Нет активных модулей</div>
                            )}
                          </div>

                          <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                            <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500 mb-4">Завершено</div>
                            {userDetail.modules_progress.completed.length > 0 ? (
                              <div className="space-y-2">
                                {userDetail.modules_progress.completed.map((m) => (
                                  <div key={m.module_id} className="flex items-center justify-between gap-4 rounded-xl bg-zinc-50 p-2 border border-zinc-100">
                                    <div className="text-[11px] font-black text-zinc-950 truncate">{m.title}</div>
                                    <div className="flex h-5 w-5 items-center justify-center rounded-full bg-[#284e13] text-[8px] text-white">✓</div>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest">Нет завершенных модулей</div>
                            )}
                          </div>
                        </div>

                        {/* Последняя история */}
                        <div className="mt-6 rounded-2xl border border-zinc-200 bg-white p-5">
                          <div className="flex items-center justify-between mb-4">
                            <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Последняя активность</div>
                            <button 
                              onClick={() => setHistoryModalOpen(true)}
                              className="text-[9px] font-black uppercase tracking-widest text-[#fe9900] hover:underline"
                            >
                              ВСЯ ИСТОРИЯ
                            </button>
                          </div>
                          <div className="space-y-2">
                            {userHistoryLoading ? (
                              <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest">Загрузка…</div>
                            ) : (
                              (userHistoryDetailed || []).slice(0, 5).map((h) => (
                                <div key={h.id} className="flex items-center justify-between gap-4 text-[11px]">
                                  <div className="min-w-0 flex-1">
                                    <div className="font-bold text-zinc-900 uppercase tracking-tight truncate">{h.title}</div>
                                    {h.subtitle ? (
                                      <div className="mt-0.5 text-[10px] font-bold text-zinc-500 uppercase tracking-tight truncate">{h.subtitle}</div>
                                    ) : null}
                                  </div>
                                  <div className="text-[10px] text-zinc-500 tabular-nums shrink-0">
                                    {new Date(h.created_at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
                                  </div>
                                </div>
                              ))
                            )}
                            {!userHistoryLoading && (!userHistoryDetailed || userHistoryDetailed.length === 0) && (
                              <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest">История пуста</div>
                            )}
                          </div>
                        </div>

                        {resetTempPassword ? (
                          <div className="mt-5 rounded-2xl border border-zinc-200 bg-white p-4">
                            <div className="flex items-center justify-between gap-4">
                              <div className="text-[9px] font-black uppercase tracking-widest text-[#fe9900]">Временный пароль</div>
                              <button
                                className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                                onClick={() => void copy(resetTempPassword)}
                                type="button"
                              >
                                КОПИРОВАТЬ
                              </button>
                            </div>
                            <div className="mt-2 text-sm font-black text-zinc-950 break-all">{resetTempPassword}</div>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  ) : (
                    <div className="mt-8 py-12 text-center text-[10px] font-black uppercase tracking-widest text-zinc-600">
                      {selectedUserId ? "НЕТ ДАННЫХ" : "ВЫБЕРИТЕ СОТРУДНИКА"}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
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
