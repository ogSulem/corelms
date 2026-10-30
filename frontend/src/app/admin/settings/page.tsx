"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, HardDrive, ImageIcon, KeyRound, Loader2, PlugZap, RefreshCw, Save, ShieldCheck, SlidersHorizontal, Sparkles, Trash2 } from "lucide-react";

import { AdminNav } from "@/components/admin/admin-nav";
import { AppShell } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/hooks/use-auth";

type AISettings = {
  configured: boolean;
  enabled: boolean;
  api_key_present: boolean;
  api_key_masked: string;
  api_key_source: string;
  token_error: boolean;
  model: string;
  base_url: string;
  http_referer: string;
  app_title: string;
  sources: Record<string, string>;
  stored: boolean;
  updated_at: string | null;
  secret_storage: string;
  env: { enabled: boolean; api_key_present: boolean; model: string; base_url: string };
};

type SalesSettings = {
  configured: boolean;
  spreadsheet_id: string;
  spreadsheet_url: string | null;
  service_account_present: boolean;
  service_account_email: string | null;
  api_key_present: boolean;
  api_key_masked: string;
  credentials_error: string | null;
  sources: Record<string, string>;
  stored: boolean;
  updated_at: string | null;
  env: { spreadsheet_id_present: boolean; service_account_present: boolean; api_key_present: boolean };
};

type StorageSettings = {
  configured: boolean;
  stored: boolean;
  updated_at: string | null;
  fields: Record<string, string>;
  overrides: Record<string, string>;
  access_key_masked: string;
  secret_key_masked: string;
  sources: Record<string, string>;
  credentials_error: boolean;
  legacy: boolean;
  effective: { bucket: string; endpoint: string; public_endpoint: string };
  command?: never;
};

type PlatformSettings = {
  upload_max_bytes: number;
  allow_public_register: boolean;
  session_idle_hours: number;
  session_absolute_days: number;
  session_refresh_days: number;
  sources: Record<string, string>;
  stored: boolean;
  updated_at: string | null;
  env: {
    upload_max_bytes: number;
    allow_public_register: boolean;
    session_idle_hours: number;
    session_absolute_days: number;
    session_refresh_days: number;
  };
  limits: {
    min_upload_bytes: number;
    max_upload_bytes: number;
    min_session_idle_hours: number;
    max_session_idle_hours: number;
    min_session_days: number;
    max_session_days: number;
  };
};

type SecurityCheck = { key: string; ok: boolean; title: string; detail: string };

type SecurityPosture = {
  client: { ip: string | null; peer: string | null; source: string; x_forwarded_for: string | null; x_real_ip: string | null };
  proxy: { trust_headers: boolean; trusted: boolean; trusted_ranges: string[] };
  request: { protocol: string; host: string; secure: boolean };
  cookies: {
    access: { name: string; http_only: boolean; same_site: string; secure: boolean; effective_secure?: boolean; domain: string | null; max_age_seconds: number | null };
    refresh: { name: string; http_only: boolean; same_site: string; secure: boolean; effective_secure?: boolean; domain: string | null; max_age_days: number };
  };
  sessions: { idle_hours: number; absolute_days: number; refresh_days: number; tracked_sessions: number; sources: Record<string, string | undefined> };
  checks: SecurityCheck[];
};

type ThumbStatus = { previewable: number; states: Record<string, number>; thumb_bytes: number };

type ServerError = {
  ts: string;
  rid: string;
  method: string;
  path: string;
  status: number;
  user_id: string | null;
  duration_ms: number | null;
  error?: string;
  traceback?: string;
};

type ServerErrors = { items: ServerError[]; count: number; log_file: string | null; hint: string | null };

type Overview = {
  app_env: string;
  public_app_url: string;
  upload_max_bytes: number;
  s3_bucket: string;
  s3_endpoint: string;
  media_dispatcher_enabled: boolean;
  schema: { current: string | null; expected: string; up_to_date: boolean };
  queue: { media: string; regen: string; workers: number | null; regen_pending: number | null };
};

const field = "w-full rounded-xl border border-zinc-200 bg-white px-3 py-2.5 text-sm text-zinc-900 outline-none transition placeholder:text-zinc-400 focus:border-amber-400 focus:ring-2 focus:ring-amber-100";
const card = "rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm shadow-zinc-950/5 sm:p-6";
const btn = "h-10";

// Shown until the live catalogue arrives; the server list is authoritative.
const FALLBACK_MODELS = ["openai/gpt-4o-mini", "openai/gpt-4.1-mini", "google/gemini-2.0-flash-001"];

type AIModelRow = { id: string; name: string; free: boolean; context: number };

const sourceLabel = (source?: string) =>
  source === "database" ? "сохранено в LMS" : source === "runtime" ? "старое серверное переопределение" : source === "environment" ? "переменная окружения" : source === "unreadable" ? "не читается" : "не задано";

function toast(title: string, description = "") {
  window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title, description } }));
}

function errorText(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export default function AdminSettingsPage() {
  const { user, loading } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";
  const isSuperadmin = user?.role === "superadmin";

  const [ai, setAi] = useState<AISettings | null>(null);
  const [aiDraft, setAiDraft] = useState({ enabled: true, api_key: "", clear_api_key: false, model: "", base_url: "", http_referer: "", app_title: "" });
  const [sales, setSales] = useState<SalesSettings | null>(null);
  const [salesDraft, setSalesDraft] = useState({ spreadsheet_id: "", service_account_json: "", api_key: "", clear_service_account: false, clear_api_key: false });
  const [serverErrors, setServerErrors] = useState<ServerErrors | null>(null);
  const [loadingErrors, setLoadingErrors] = useState(false);
  const [storageSettings, setStorageSettings] = useState<StorageSettings | null>(null);
  const [storageDraft, setStorageDraft] = useState({ s3_endpoint_url: "", s3_public_endpoint_url: "", s3_bucket: "", s3_region_name: "", s3_addressing_style: "", s3_access_key_id: "", s3_secret_access_key: "" });
  const [savingStorage, setSavingStorage] = useState(false);
  const [testingStorage, setTestingStorage] = useState(false);
  const [storageTest, setStorageTest] = useState<{ ok: boolean; message: string } | null>(null);
  const [platform, setPlatform] = useState<PlatformSettings | null>(null);
  const [platformDraft, setPlatformDraft] = useState({ upload_mb: 512, allow_public_register: false, session_idle_hours: 12, session_absolute_days: 30, session_refresh_days: 30 });
  const [savingPlatform, setSavingPlatform] = useState(false);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loadingData, setLoadingData] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingAI, setSavingAI] = useState(false);
  const [testingAI, setTestingAI] = useState(false);
  const [aiTest, setAiTest] = useState<{ ok: boolean; message: string } | null>(null);
  const [aiModels, setAiModels] = useState<AIModelRow[] | null>(null);
  const [loadingModels, setLoadingModels] = useState(false);
  const [savingSales, setSavingSales] = useState(false);
  const [testingSales, setTestingSales] = useState(false);
  const [salesTest, setSalesTest] = useState<{ ok: boolean; message: string } | null>(null);
  const [health, setHealth] = useState<{ ok: boolean; message: string; at: string } | null>(null);
  const [checkingHealth, setCheckingHealth] = useState(false);
  const [security, setSecurity] = useState<SecurityPosture | null>(null);
  const [loadingSecurity, setLoadingSecurity] = useState(false);
  const [thumbs, setThumbs] = useState<ThumbStatus | null>(null);
  const [warmingThumbs, setWarmingThumbs] = useState(false);

  const applyAI = useCallback((data: AISettings) => {
    setAi(data);
    setAiDraft({ enabled: data.enabled, api_key: "", clear_api_key: false, model: data.model, base_url: data.base_url, http_referer: data.http_referer, app_title: data.app_title });
  }, []);

  const applyStorage = useCallback((data: StorageSettings) => {
    setStorageSettings(data);
    setStorageDraft({
      s3_endpoint_url: data.overrides.s3_endpoint_url || "",
      s3_public_endpoint_url: data.overrides.s3_public_endpoint_url || "",
      s3_bucket: data.overrides.s3_bucket || data.effective.bucket || "",
      s3_region_name: data.overrides.s3_region_name || "",
      s3_addressing_style: data.overrides.s3_addressing_style || "",
      s3_access_key_id: "",
      s3_secret_access_key: "",
    });
  }, []);

  const platformValid = Number.isFinite(platformDraft.upload_mb) && platformDraft.upload_mb >= 1 && platformDraft.upload_mb <= 20480
    && platformDraft.session_idle_hours >= 1 && platformDraft.session_idle_hours <= 168
    && platformDraft.session_absolute_days >= 1 && platformDraft.session_absolute_days <= 365
    && platformDraft.session_refresh_days >= 1 && platformDraft.session_refresh_days <= 365;

  const applyPlatform = useCallback((data: PlatformSettings) => {
    setPlatform(data);
    setPlatformDraft({
      upload_mb: Math.max(1, Math.round(data.upload_max_bytes / (1024 * 1024))),
      allow_public_register: data.allow_public_register,
      session_idle_hours: data.session_idle_hours,
      session_absolute_days: data.session_absolute_days,
      session_refresh_days: data.session_refresh_days,
    });
  }, []);

  const applySales = useCallback((data: SalesSettings) => {
    setSales(data);
    setSalesDraft({ spreadsheet_id: data.spreadsheet_id, service_account_json: "", api_key: "", clear_service_account: false, clear_api_key: false });
  }, []);

  const load = useCallback(async () => {
    setError(null);
    setLoadingData(true);
    try {
      const [aiData, overviewData, storageData, platformData] = await Promise.all([
        apiFetch<AISettings>("/admin/settings/ai"),
        apiFetch<Overview>("/admin/settings/overview"),
        apiFetch<StorageSettings>("/admin/settings/storage"),
        apiFetch<PlatformSettings>("/admin/settings/platform"),
      ]);
      applyAI(aiData);
      setOverview(overviewData);
      applyStorage(storageData);
      applyPlatform(platformData);
      void loadThumbs();
      if (isSuperadmin) {
        try {
          applySales(await apiFetch<SalesSettings>("/admin/settings/sales"));
        } catch (salesError) {
          setError(errorText(salesError, "Не удалось загрузить настройки продаж"));
        }
      }
    } catch (loadError) {
      setError(errorText(loadError, "Не удалось загрузить настройки"));
    } finally {
      setLoadingData(false);
    }
  }, [applyAI, applyPlatform, applySales, applyStorage, isSuperadmin]);

  useEffect(() => {
    if (!loading && isAdmin) void load();
  }, [isAdmin, load, loading]);

  const loadErrors = useCallback(async () => {
    setLoadingErrors(true);
    try {
      setServerErrors(await apiFetch<ServerErrors>("/admin/diagnostics/errors?limit=20"));
    } catch (errorsError) {
      setServerErrors({ items: [], count: 0, log_file: null, hint: errorText(errorsError, "Не удалось прочитать журнал ошибок") });
    } finally {
      setLoadingErrors(false);
    }
  }, []);

  useEffect(() => {
    if (!loading && isAdmin) void loadErrors();
  }, [isAdmin, loadErrors, loading]);

  const checkHealth = useCallback(async () => {
    if (checkingHealth) return;
    setCheckingHealth(true);
    try {
      // /health/ready проверяет базу, Redis и S3 одним запросом.
      await apiFetch<{ status: string }>("/health/ready", { timeoutMs: 20_000 });
      setHealth({ ok: true, message: "База данных, Redis и хранилище S3 отвечают.", at: new Date().toLocaleTimeString("ru-RU") });
    } catch (healthError) {
      setHealth({ ok: false, message: errorText(healthError, "Сервис не отвечает"), at: new Date().toLocaleTimeString("ru-RU") });
    } finally {
      setCheckingHealth(false);
    }
  }, [checkingHealth]);

  useEffect(() => {
    if (!loading && isAdmin) void checkHealth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, isAdmin]);

  const aiStatus = useMemo(() => {
    if (!ai) return { label: "Проверяем…", tone: "zinc" as const };
    if (ai.token_error) return { label: "Токен не читается", tone: "red" as const };
    if (!ai.enabled) return { label: "AI отключён", tone: "zinc" as const };
    if (!ai.api_key_present) return { label: "Нужен токен", tone: "amber" as const };
    return { label: "Готово к генерации", tone: "green" as const };
  }, [ai]);

  async function saveAI() {
    if (savingAI) return;
    setSavingAI(true);
    setError(null);
    try {
      const data = await apiFetch<{ settings: AISettings }>("/admin/settings/ai", {
        method: "PUT",
        body: JSON.stringify({
          enabled: aiDraft.enabled,
          api_key: aiDraft.api_key.trim() ? aiDraft.api_key.trim() : null,
          clear_api_key: aiDraft.clear_api_key,
          model: aiDraft.model.trim(),
          base_url: aiDraft.base_url.trim(),
          http_referer: aiDraft.http_referer.trim(),
          app_title: aiDraft.app_title.trim(),
        }),
      });
      applyAI(data.settings);
      setAiTest(null);
      toast("Настройки AI сохранены", "Токен зашифрован и уже доступен воркерам");
    } catch (saveError) {
      setError(errorText(saveError, "Не удалось сохранить настройки AI"));
    } finally {
      setSavingAI(false);
    }
  }

  async function loadModels() {
    if (loadingModels) return;
    setLoadingModels(true);
    setError(null);
    try {
      const result = await apiFetch<{ ok: boolean; count: number; free_count: number; models: AIModelRow[]; message: string }>(
        "/admin/settings/ai/models",
        {
          method: "POST",
          body: JSON.stringify({
            api_key: aiDraft.api_key.trim() || null,
            base_url: aiDraft.base_url.trim() || null,
          }),
          timeoutMs: 30_000,
        },
      );
      setAiModels(result.models || []);
      setAiTest({ ok: Boolean(result.ok), message: String(result.message || "") });
      if (result.ok && result.models?.length) {
        toast("Список моделей загружен", `Доступно ${result.count}, бесплатных ${result.free_count}`);
      }
    } catch (modelsError) {
      setAiTest({ ok: false, message: errorText(modelsError, "Не удалось загрузить список моделей") });
    } finally {
      setLoadingModels(false);
    }
  }

  async function testAI() {
    if (testingAI) return;
    setTestingAI(true);
    setAiTest(null);
    setError(null);
    try {
      const result = await apiFetch<{ ok: boolean; message: string }>("/admin/settings/ai/test", {
        method: "POST",
        body: JSON.stringify({
          api_key: aiDraft.api_key.trim() || null,
          base_url: aiDraft.base_url.trim() || null,
          model: aiDraft.model.trim() || null,
        }),
        timeoutMs: 30_000,
      });
      const suffix = result.ok && aiDraft.api_key.trim() ? " Нажмите «Сохранить», чтобы AI начал работать." : "";
      setAiTest({ ok: Boolean(result.ok), message: String(result.message || (result.ok ? "Подключение работает" : "Не удалось подключиться")) + suffix });
    } catch (testError) {
      setAiTest({ ok: false, message: errorText(testError, "Не удалось проверить подключение") });
    } finally {
      setTestingAI(false);
    }
  }

  async function resetAI() {
    if (!window.confirm("Сбросить настройки AI? Сохранённый в LMS токен будет удалён, приложение вернётся к переменным окружения.")) return;
    setSavingAI(true);
    setError(null);
    try {
      const data = await apiFetch<{ settings: AISettings }>("/admin/settings/ai", { method: "DELETE" });
      applyAI(data.settings);
      setAiTest(null);
      toast("Настройки AI сброшены", "Используются значения сервера");
    } catch (resetError) {
      setError(errorText(resetError, "Не удалось сбросить настройки AI"));
    } finally {
      setSavingAI(false);
    }
  }

  async function saveSales() {
    if (savingSales) return;
    setSavingSales(true);
    setError(null);
    try {
      const data = await apiFetch<{ settings: SalesSettings }>("/admin/settings/sales", {
        method: "PUT",
        body: JSON.stringify({
          spreadsheet_id: salesDraft.spreadsheet_id.trim(),
          service_account_json: salesDraft.service_account_json.trim() || null,
          api_key: salesDraft.api_key.trim() || null,
          clear_service_account: salesDraft.clear_service_account,
          clear_api_key: salesDraft.clear_api_key,
        }),
      });
      applySales(data.settings);
      setSalesTest(null);
      toast("Настройки продаж сохранены", "Ссылки обновятся при следующем открытии раздела");
    } catch (saveError) {
      setError(errorText(saveError, "Не удалось сохранить настройки продаж"));
    } finally {
      setSavingSales(false);
    }
  }

  async function testSales() {
    if (testingSales) return;
    setTestingSales(true);
    setSalesTest(null);
    setError(null);
    try {
      const result = await apiFetch<{ ok: boolean; message: string; service_account_email?: string | null }>("/admin/settings/sales/test", {
        method: "POST",
        body: JSON.stringify({
          spreadsheet_id: salesDraft.spreadsheet_id.trim() || null,
          service_account_json: salesDraft.service_account_json.trim() || null,
          api_key: salesDraft.api_key.trim() || null,
          use_saved: true,
        }),
        timeoutMs: 20_000,
      });
      const suffix = result.ok && result.service_account_email ? ` Если доступа нет, откройте таблицу для ${result.service_account_email} с правом «Читатель».` : "";
      setSalesTest({ ok: Boolean(result.ok), message: String(result.message || "") + (result.ok ? suffix : "") });
    } catch (testError) {
      setSalesTest({ ok: false, message: errorText(testError, "Не удалось прочитать таблицу") });
    } finally {
      setTestingSales(false);
    }
  }

  async function resetSales() {
    if (!window.confirm("Сбросить настройки Google Sheets? Файлы продаж продолжат работать.")) return;
    setSavingSales(true);
    setError(null);
    try {
      const data = await apiFetch<{ settings: SalesSettings }>("/admin/settings/sales", { method: "DELETE" });
      applySales(data.settings);
      setSalesTest(null);
      toast("Настройки продаж сброшены", "Используются значения сервера");
    } catch (resetError) {
      setError(errorText(resetError, "Не удалось сбросить настройки продаж"));
    } finally {
      setSavingSales(false);
    }
  }

  async function saveStorage() {
    if (savingStorage) return;
    setSavingStorage(true);
    setError(null);
    try {
      const data = await apiFetch<{ settings: StorageSettings }>("/admin/settings/storage", {
        method: "PUT",
        body: JSON.stringify({
          s3_endpoint_url: storageDraft.s3_endpoint_url.trim(),
          s3_public_endpoint_url: storageDraft.s3_public_endpoint_url.trim(),
          s3_bucket: storageDraft.s3_bucket.trim(),
          s3_region_name: storageDraft.s3_region_name.trim(),
          s3_addressing_style: storageDraft.s3_addressing_style.trim(),
          s3_access_key_id: storageDraft.s3_access_key_id.trim() || null,
          s3_secret_access_key: storageDraft.s3_secret_access_key.trim() || null,
        }),
      });
      applyStorage(data.settings);
      setStorageTest(null);
      toast("Хранилище сохранено", "Новые значения уже действуют для загрузок и воркеров");
      setOverview(await apiFetch<Overview>("/admin/settings/overview"));
    } catch (saveError) {
      setError(errorText(saveError, "Не удалось сохранить настройки хранилища"));
    } finally {
      setSavingStorage(false);
    }
  }

  async function testStorage() {
    if (testingStorage) return;
    setTestingStorage(true);
    setStorageTest(null);
    setError(null);
    try {
      const result = await apiFetch<{ ok: boolean; message: string; bucket?: string }>("/admin/settings/storage/test", {
        method: "POST",
        body: JSON.stringify({}),
        timeoutMs: 20_000,
      });
      setStorageTest({ ok: Boolean(result.ok), message: String(result.message || "") });
    } catch (testError) {
      setStorageTest({ ok: false, message: errorText(testError, "Не удалось проверить хранилище") });
    } finally {
      setTestingStorage(false);
    }
  }

  async function resetStorage() {
    if (!window.confirm("Вернуть хранилищу значения сервера (.env)? Уже загруженные файлы не удаляются.")) return;
    setSavingStorage(true);
    setError(null);
    try {
      const data = await apiFetch<{ settings: StorageSettings }>("/admin/settings/storage", { method: "DELETE" });
      applyStorage(data.settings);
      setStorageTest(null);
      toast("Хранилище сброшено к серверу", "Используются значения из .env");
      setOverview(await apiFetch<Overview>("/admin/settings/overview"));
    } catch (resetError) {
      setError(errorText(resetError, "Не удалось сбросить настройки хранилища"));
    } finally {
      setSavingStorage(false);
    }
  }

  async function savePlatform() {
    if (savingPlatform) return;
    setSavingPlatform(true);
    setError(null);
    try {
      const bytes = Math.round(Number(platformDraft.upload_mb) * 1024 * 1024);
      const data = await apiFetch<{ settings: PlatformSettings }>("/admin/settings/platform", {
        method: "PUT",
        body: JSON.stringify({
          upload_max_bytes: bytes,
          allow_public_register: platformDraft.allow_public_register,
          session_idle_hours: platformDraft.session_idle_hours,
          session_absolute_days: platformDraft.session_absolute_days,
          session_refresh_days: platformDraft.session_refresh_days,
        }),
      });
      applyPlatform(data.settings);
      toast("Настройки платформы сохранены", "Действуют сразу: загрузки, регистрация и сроки сессий");
      setOverview(await apiFetch<Overview>("/admin/settings/overview"));
    } catch (saveError) {
      setError(errorText(saveError, "Не удалось сохранить настройки платформы"));
    } finally {
      setSavingPlatform(false);
    }
  }

  async function resetPlatform() {
    if (!window.confirm("Вернуть лимиты и регистрацию к значениям сервера (.env)?")) return;
    setSavingPlatform(true);
    setError(null);
    try {
      const data = await apiFetch<{ settings: PlatformSettings }>("/admin/settings/platform", { method: "DELETE" });
      applyPlatform(data.settings);
      toast("Возвращены значения сервера", "Правила .env снова действуют");
      setOverview(await apiFetch<Overview>("/admin/settings/overview"));
    } catch (resetError) {
      setError(errorText(resetError, "Не удалось сбросить настройки платформы"));
    } finally {
      setSavingPlatform(false);
    }
  }

  async function loadSecurity() {
    if (loadingSecurity) return;
    setLoadingSecurity(true);
    setError(null);
    try {
      setSecurity(await apiFetch<SecurityPosture>("/admin/settings/security"));
    } catch (securityError) {
      setError(errorText(securityError, "Не удалось проверить безопасность"));
    } finally {
      setLoadingSecurity(false);
    }
  }

  async function loadThumbs() {
    try {
      setThumbs(await apiFetch<ThumbStatus>("/admin/maintenance/thumbs/status"));
    } catch {
      setThumbs(null); // диагностика не критична: файлы работают и без превью
    }
  }

  async function warmThumbs() {
    if (warmingThumbs) return;
    setWarmingThumbs(true);
    setError(null);
    try {
      const result = await apiFetch<{ queued: number }>("/admin/maintenance/thumbs/backfill", { method: "POST" });
      toast("Превью поставлены в очередь", result.queued ? `${result.queued} файлов обработаются в фоне` : "Все файлы уже с превью");
      await loadThumbs();
    } catch (warmError) {
      setError(errorText(warmError, "Не удалось поставить превью в очередь"));
    } finally {
      setWarmingThumbs(false);
    }
  }

  if (loading) {
    return <AppShell><p role="status" className="p-10 text-center text-sm text-zinc-500">Проверяем доступ…</p></AppShell>;
  }
  if (!isAdmin) {
    return <AppShell><p role="alert" className="p-10 text-center text-sm text-zinc-700">Раздел доступен только администраторам.</p></AppShell>;
  }

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:py-10">
        <div className="mb-7 flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-amber-800">Админ-центр</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-950">Настройки</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-600">
              Все ключи платформы в одном месте: AI для черновиков тестов, таблица продаж, файловое хранилище и состояние сервера. Секреты шифруются и никогда не показываются целиком.
            </p>
          </div>
          
        </div>
        <AdminNav />

        <nav aria-label="Разделы настроек" className="mb-6 flex flex-wrap gap-2 text-sm">
          {[
            { href: "#ai", label: "AI для тестов" },
            { href: "#sales", label: "Продажи (Sheets)" },
            { href: "#storage", label: "Хранилище файлов" },
            { href: "#platform", label: "Платформа" },
            { href: "#security", label: "Безопасность и доступ" },
            { href: "#system", label: "Сервер и схема" },
            { href: "#errors", label: "Ошибки сервера" },
          ].map((item) => (
            <a key={item.href} href={item.href} className="rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-zinc-600 transition hover:border-zinc-300 hover:text-zinc-900">
              {item.label}
            </a>
          ))}
        </nav>

        {error && <div role="alert" className="mb-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div>}

        {loadingData ? (
          <div className={card}><p role="status" className="flex items-center gap-2 text-sm text-zinc-500"><Loader2 size={16} className="animate-spin" />Загружаем настройки…</p></div>
        ) : (
          <div className="space-y-6">
            <section id="ai" className={`${card} scroll-mt-24`} aria-labelledby="ai-title">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 rounded-xl bg-amber-50 p-2 text-amber-700"><Sparkles size={18} /></span>
                  <div>
                    <h2 id="ai-title" className="text-lg font-semibold text-zinc-950">AI для тестов</h2>
                    <p className="mt-1 text-sm leading-6 text-zinc-600">Токен OpenRouter (или совместимого API) для черновиков вопросов. Сохранение не требует перезапуска.</p>
                  </div>
                </div>
                <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${
                  aiStatus.tone === "green" ? "bg-emerald-50 text-emerald-800" : aiStatus.tone === "amber" ? "bg-amber-50 text-amber-900" : aiStatus.tone === "red" ? "bg-red-50 text-red-800" : "bg-zinc-100 text-zinc-700"
                }`}>
                  {aiStatus.tone === "green" ? <CheckCircle2 size={13} /> : aiStatus.tone === "red" ? <AlertTriangle size={13} /> : <KeyRound size={13} />}
                  {aiStatus.label}
                </span>
              </div>

              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                <label className="block space-y-2 text-sm font-medium sm:col-span-2">
                  API-токен
                  <input
                    type="password"
                    autoComplete="new-password"
                    className={field}
                    value={aiDraft.api_key}
                    placeholder={ai?.api_key_present ? `Сохранён: ${ai.api_key_masked}. Оставьте пустым, чтобы не менять.` : "sk-or-v1-…"}
                    onChange={(event) => setAiDraft((prev) => ({ ...prev, api_key: event.target.value, clear_api_key: false, enabled: event.target.value.trim() ? true : prev.enabled }))}
                  />
                  <span className="block text-xs font-normal leading-5 text-zinc-500">
                    Источник: {sourceLabel(ai?.api_key_source)}{ai?.secret_storage === "encrypted" ? " · хранится в зашифрованном виде" : ""}.
                    {ai?.token_error ? " Текущий ключ шифрования изменился — введите токен заново." : ""}
                  </span>
                </label>
                <label className="flex items-center gap-2 rounded-xl border border-zinc-200 px-3 py-2.5 text-sm">
                  <input type="checkbox" checked={aiDraft.enabled} onChange={(event) => setAiDraft((prev) => ({ ...prev, enabled: event.target.checked }))} />
                  Использовать AI для черновиков
                </label>
                <label className="flex items-center gap-2 rounded-xl border border-zinc-200 px-3 py-2.5 text-sm">
                  <input type="checkbox" checked={aiDraft.clear_api_key} onChange={(event) => setAiDraft((prev) => ({ ...prev, clear_api_key: event.target.checked, api_key: event.target.checked ? "" : prev.api_key }))} />
                  Удалить сохранённый токен
                </label>
                <label className="block space-y-2 text-sm font-medium">
                  Модель
                  <div className="flex flex-wrap gap-2">
                    <input list="ai-models" className={`${field} min-w-0 flex-1`} value={aiDraft.model} placeholder="openai/gpt-4o-mini" onChange={(event) => setAiDraft((prev) => ({ ...prev, model: event.target.value }))} />
                    <Button variant="outline" className={btn} onClick={() => void loadModels()} disabled={loadingModels}>
                      {loadingModels ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}Загрузить модели
                    </Button>
                  </div>
                  <datalist id="ai-models">
                    {(aiModels ?? FALLBACK_MODELS.map((id) => ({ id, name: id, free: false, context: 0 }))).map((model) => (
                      <option key={model.id} value={model.id}>{model.free ? `${model.name} · бесплатно` : model.name}</option>
                    ))}
                  </datalist>
                  <span className="block text-xs font-normal leading-5 text-zinc-500">
                    {aiModels
                      ? `Список с сервера: ${aiModels.length} моделей, бесплатных ${aiModels.filter((model) => model.free).length}. Начните вводить название — браузер подскажет доступные.`
                      : "Нажмите «Загрузить модели», чтобы увидеть, что реально доступно вашему токену (бесплатные — первыми)."}
                  </span>
                </label>
                <label className="block space-y-2 text-sm font-medium">
                  Адрес API
                  <input className={field} value={aiDraft.base_url} placeholder="https://openrouter.ai/api/v1" onChange={(event) => setAiDraft((prev) => ({ ...prev, base_url: event.target.value }))} />
                  <span className="block text-xs font-normal leading-5 text-zinc-500">Пусто — значение сервера ({ai?.env.base_url || "не задано"}).</span>
                </label>
                <details className="sm:col-span-2">
                  <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-zinc-500">Дополнительно</summary>
                  <div className="mt-3 grid gap-4 sm:grid-cols-2">
                    <label className="block space-y-2 text-sm font-medium">
                      HTTP-Referer
                      <input className={field} value={aiDraft.http_referer} onChange={(event) => setAiDraft((prev) => ({ ...prev, http_referer: event.target.value }))} placeholder="https://lms.example.com" />
                    </label>
                    <label className="block space-y-2 text-sm font-medium">
                      Название приложения
                      <input className={field} value={aiDraft.app_title} onChange={(event) => setAiDraft((prev) => ({ ...prev, app_title: event.target.value }))} placeholder="CoreLMS" />
                    </label>
                  </div>
                </details>
              </div>

              {aiTest && (
                <p role="status" className={`mt-4 rounded-xl px-4 py-3 text-sm ${aiTest.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"}`}>
                  {aiTest.message}
                </p>
              )}

              <div className="mt-5 flex flex-wrap gap-2">
                <Button className={btn} onClick={() => void saveAI()} disabled={savingAI}>
                  {savingAI ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}Сохранить
                </Button>
                <Button variant="outline" className={btn} onClick={() => void testAI()} disabled={testingAI}>
                  {testingAI ? <Loader2 size={16} className="animate-spin" /> : <PlugZap size={16} />}Проверить подключение
                </Button>
                <Button variant="outline" className={btn} onClick={() => void resetAI()} disabled={savingAI || !ai?.stored}>
                  <RefreshCw size={16} />Сбросить к серверу
                </Button>
              </div>

              {overview && overview.queue.workers === 0 && (
                <p role="status" className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                  Фоновые воркеры не запущены: черновики будут создаваться, но останутся в очереди. Запустите <code className="rounded bg-white/70 px-1 py-0.5 text-xs">worker_regen</code>.
                </p>
              )}
              {overview && overview.queue.workers === null && (
                <p role="status" className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                  Нет связи с Redis — очередь генерации недоступна. Проверьте контейнер Redis и настройки подключения.
                </p>
              )}

              <div className="mt-5 rounded-xl bg-zinc-50 p-4 text-xs leading-6 text-zinc-600">
                <p className="font-semibold text-zinc-800">Как появляются тесты</p>
                <ol className="mt-1 list-decimal space-y-1 pl-4">
                  <li>В редакторе модуля откройте «Тесты» и выберите урок.</li>
                  <li>AI получает текст урока, документ (PDF/DOCX/PPTX) или вставленный фрагмент — первые 12 000 символов — и возвращает черновик. Сканы без текстового слоя и видео автоматически не распознаются.</li>
                  <li>Черновик не публикуется автоматически: проверьте вопросы и нажмите «Сохранить тест».</li>
                  <li>Можно подготовить черновики сразу для всех уроков модуля — до 50 за запуск.</li>
                  <li>Без AI тесты создаются вручную; остальная работа модуля не зависит от токена.</li>
                </ol>
              </div>
            </section>

            <section id="sales" className={`${card} scroll-mt-24`} aria-labelledby="sales-title">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 rounded-xl bg-emerald-50 p-2 text-emerald-700"><ShieldCheck size={18} /></span>
                <div>
                  <h2 id="sales-title" className="text-lg font-semibold text-zinc-950">Google Sheets для раздела «Продажи»</h2>
                  <p className="mt-1 text-sm leading-6 text-zinc-600">Таблица только читается. Файлы продаж в S3 работают и без неё.</p>
                </div>
              </div>

              {!isSuperadmin ? (
                <p className="mt-4 rounded-xl bg-zinc-50 px-4 py-3 text-sm text-zinc-600">Настройка таблицы доступна супер-администратору.</p>
              ) : (
                <>
                  <div className="mt-5 grid gap-4">
                    <label className="block space-y-2 text-sm font-medium">
                      Идентификатор таблицы
                      <input className={field} value={salesDraft.spreadsheet_id} onChange={(event) => setSalesDraft((prev) => ({ ...prev, spreadsheet_id: event.target.value }))} placeholder="1AbC… — часть ссылки между /d/ и /edit" />
                      {sales?.spreadsheet_url && <a href={sales.spreadsheet_url} target="_blank" rel="noreferrer" className="block text-xs font-normal text-amber-800 underline">Открыть таблицу</a>}
                    </label>
                    <label className="block space-y-2 text-sm font-medium">
                      JSON сервисного аккаунта
                      <textarea rows={3} className={field} value={salesDraft.service_account_json} onChange={(event) => setSalesDraft((prev) => ({ ...prev, service_account_json: event.target.value, clear_service_account: false }))} placeholder={sales?.service_account_present ? "Ключ уже сохранён. Оставьте пустым, чтобы не менять." : "Вставьте содержимое JSON-файла сервисного аккаунта"} />
                      {sales?.service_account_email && <span className="block text-xs font-normal text-zinc-500">Откройте таблицу для {sales.service_account_email} с правом «Читатель».</span>}
                    </label>
                    <label className="block space-y-2 text-sm font-medium">
                      …или Google API key
                      <input type="password" autoComplete="new-password" className={field} value={salesDraft.api_key} onChange={(event) => setSalesDraft((prev) => ({ ...prev, api_key: event.target.value, clear_api_key: false }))} placeholder={sales?.api_key_present ? `Сохранён: ${sales.api_key_masked}` : "Для таблицы, открытой по ссылке"} />
                    </label>
                    <div className="flex flex-wrap gap-4 text-sm">
                      <label className="flex items-center gap-2"><input type="checkbox" checked={salesDraft.clear_service_account} onChange={(event) => setSalesDraft((prev) => ({ ...prev, clear_service_account: event.target.checked, service_account_json: event.target.checked ? "" : prev.service_account_json }))} />Удалить JSON аккаунта</label>
                      <label className="flex items-center gap-2"><input type="checkbox" checked={salesDraft.clear_api_key} onChange={(event) => setSalesDraft((prev) => ({ ...prev, clear_api_key: event.target.checked, api_key: event.target.checked ? "" : prev.api_key }))} />Удалить API key</label>
                    </div>
                  </div>

                  {salesTest && (
                    <p role="status" className={`mt-4 rounded-xl px-4 py-3 text-sm ${salesTest.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"}`}>{salesTest.message}</p>
                  )}

                  <div className="mt-5 flex flex-wrap gap-2">
                    <Button className={btn} onClick={() => void saveSales()} disabled={savingSales}>
                      {savingSales ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}Сохранить
                    </Button>
                    <Button variant="outline" className={btn} onClick={() => void testSales()} disabled={testingSales}>
                      {testingSales ? <Loader2 size={16} className="animate-spin" /> : <PlugZap size={16} />}Проверить таблицу
                    </Button>
                    <Button variant="outline" className={btn} onClick={() => void resetSales()} disabled={savingSales || !sales?.stored}>
                      <Trash2 size={16} />Сбросить к серверу
                    </Button>
                  </div>
                </>
              )}
            </section>

            <section id="storage" className={`${card} scroll-mt-24`} aria-labelledby="storage-title">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 rounded-xl bg-sky-50 p-2 text-sky-700"><HardDrive size={18} /></span>
                <div>
                  <h2 id="storage-title" className="text-lg font-semibold text-zinc-950">Хранилище файлов (S3)</h2>
                  <p className="mt-1 text-sm leading-6 text-zinc-600">
                    Куда сохраняются материалы, видео и ZIP-архивы. Значения действуют сразу, без перезапуска; сброс возвращает <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs">.env</code>.
                  </p>
                </div>
              </div>

              {storageSettings?.credentials_error ? (
                <p role="alert" className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                  Сохранённые ключи хранилища не читаются (изменился ключ шифрования). Загрузите файлы пока работают значения сервера — введите ключи заново.
                </p>
              ) : null}
              {storageSettings?.legacy ? (
                <p role="status" className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                  Действуют старые настройки из Redis. Сохраните значения здесь — они перейдут в защищённое хранилище приложения.
                </p>
              ) : null}

              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                <label className="block space-y-2 text-sm font-medium">
                  Bucket
                  <input className={field} value={storageDraft.s3_bucket} onChange={(event) => setStorageDraft((prev) => ({ ...prev, s3_bucket: event.target.value }))} placeholder="corelms-content"  />
                </label>
                <label className="block space-y-2 text-sm font-medium">
                  Адрес API хранилища
                  <input className={field} value={storageDraft.s3_endpoint_url} onChange={(event) => setStorageDraft((prev) => ({ ...prev, s3_endpoint_url: event.target.value }))} placeholder="https://s3.regru.cloud"  />
                </label>
                <label className="block space-y-2 text-sm font-medium">
                  Публичный адрес для браузера
                  <input className={field} value={storageDraft.s3_public_endpoint_url} onChange={(event) => setStorageDraft((prev) => ({ ...prev, s3_public_endpoint_url: event.target.value }))} placeholder="тот же адрес, если доступен извне"  />
                </label>
                <label className="block space-y-2 text-sm font-medium">
                  Регион
                  <input className={field} value={storageDraft.s3_region_name} onChange={(event) => setStorageDraft((prev) => ({ ...prev, s3_region_name: event.target.value }))} placeholder="us-east-1"  />
                </label>
                <label className="block space-y-2 text-sm font-medium">
                  Access key ID
                  <input className={field} value={storageDraft.s3_access_key_id} onChange={(event) => setStorageDraft((prev) => ({ ...prev, s3_access_key_id: event.target.value }))} placeholder={storageSettings?.access_key_masked ? `Сохранён: ${storageSettings.access_key_masked}` : "Ключ доступа"}  />
                </label>
                <label className="block space-y-2 text-sm font-medium">
                  Secret access key
                  <input type="password" autoComplete="new-password" className={field} value={storageDraft.s3_secret_access_key} onChange={(event) => setStorageDraft((prev) => ({ ...prev, s3_secret_access_key: event.target.value }))} placeholder={storageSettings?.secret_key_masked ? `Сохранён: ${storageSettings.secret_key_masked}` : "Секретный ключ"}  />
                </label>
                <details className="sm:col-span-2">
                  <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-zinc-500">Дополнительно</summary>
                  <label className="mt-3 block space-y-2 text-sm font-medium">
                    Стиль адресации
                    <input className={field} value={storageDraft.s3_addressing_style} onChange={(event) => setStorageDraft((prev) => ({ ...prev, s3_addressing_style: event.target.value }))} placeholder="path"  />
                    <span className="block text-xs font-normal leading-5 text-zinc-500">Пусто — значение сервера. Для REG.RU и MinIO обычно <code className="rounded bg-zinc-100 px-1 py-0.5">path</code>.</span>
                  </label>
                </details>
              </div>

              {storageTest && (
                <p role="status" className={`mt-4 rounded-xl px-4 py-3 text-sm ${storageTest.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"}`}>{storageTest.message}</p>
              )}

              <div className="mt-5 rounded-xl border border-zinc-200 bg-zinc-50/60 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-zinc-900">Превью фото и видео</p>
                    <p className="mt-1 text-xs leading-5 text-zinc-600">
                      Списки показывают уменьшенный кадр вместо полного файла: фото не грузится целиком, видео не скачивается ради одной картинки.
                      {thumbs ? ` С превью: ${thumbs.states.ready || 0} из ${thumbs.previewable}${thumbs.states.failed ? `, не удалось: ${thumbs.states.failed}` : ""}.` : ""}
                    </p>
                  </div>
                  <Button variant="outline" className={btn} onClick={() => void warmThumbs()} disabled={warmingThumbs}>
                    {warmingThumbs ? <Loader2 size={16} className="animate-spin" /> : <ImageIcon size={16} />}Подготовить для старых файлов
                  </Button>
                </div>
              </div>

              <div className="mt-5 flex flex-wrap gap-2">
                <Button className={btn} onClick={() => void saveStorage()} disabled={savingStorage}>
                  {savingStorage ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}Сохранить
                </Button>
                <Button variant="outline" className={btn} onClick={() => void testStorage()} disabled={testingStorage}>
                  {testingStorage ? <Loader2 size={16} className="animate-spin" /> : <PlugZap size={16} />}Проверить хранилище
                </Button>
                <Button variant="outline" className={btn} onClick={() => void resetStorage()} disabled={savingStorage || !storageSettings?.stored}>
                  <RefreshCw size={16} />Сбросить к серверу
                </Button>
              </div>

              <p className="mt-4 text-xs leading-5 text-zinc-500">
                Проверка использует уже сохранённые значения: если только что изменили поля, сначала нажмите «Сохранить».
                Действующие bucket: <span className="font-medium text-zinc-700">{storageSettings?.effective.bucket || overview?.s3_bucket || "—"}</span>
                {storageSettings?.effective.endpoint ? ` · ${storageSettings.effective.endpoint}` : ""}
                {storageSettings?.sources?.s3_bucket === "environment" ? " · из .env" : ""}
              </p>
            </section>

            <section id="platform" className={`${card} scroll-mt-24`} aria-labelledby="platform-title">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 rounded-xl bg-violet-50 p-2 text-violet-700"><SlidersHorizontal size={18} /></span>
                <div>
                  <h2 id="platform-title" className="text-lg font-semibold text-zinc-950">Платформа</h2>
                  <p className="mt-1 text-sm leading-6 text-zinc-600">
                    Ограничения, которые чаще всего приходится менять: размер файла и самостоятельная регистрация. Применяются сразу, без перезапуска.
                  </p>
                </div>
              </div>

              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                <label className="block space-y-2 text-sm font-medium">
                  Максимальный размер файла, МБ
                  <input
                    type="number"
                    min={1}
                    max={20480}
                    className={field}
                    value={platformDraft.upload_mb}
                    onChange={(event) => setPlatformDraft((prev) => ({ ...prev, upload_mb: Number(event.target.value) }))}
                  />
                  <span className="block text-xs font-normal leading-5 text-zinc-500">
                    От 1 МБ до 20 ГБ. Действует для материалов, видео и файлов продаж. В <code className="rounded bg-zinc-100 px-1 py-0.5">.env</code>: {platform ? Math.round(platform.env.upload_max_bytes / (1024 * 1024)) : "—"} МБ.
                  </span>
                </label>
                <label className="flex items-start gap-2 rounded-xl border border-zinc-200 px-3 py-2.5 text-sm">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={platformDraft.allow_public_register}
                    onChange={(event) => setPlatformDraft((prev) => ({ ...prev, allow_public_register: event.target.checked }))}
                  />
                  <span>
                    Открытая регистрация
                    <span className="mt-1 block text-xs leading-5 text-zinc-500">
                      Если выключено, новых учеников создаёт администратор в разделе «Пользователи» — это безопасный режим по умолчанию.
                    </span>
                  </span>
                </label>
              </div>

              <div className="mt-5 grid gap-4 sm:grid-cols-3">
                <label className="block space-y-2 text-sm font-medium">
                  Простой сессии, ч
                  <input type="number" min={1} max={168} className={field} value={platformDraft.session_idle_hours}
                    onChange={(event) => setPlatformDraft((prev) => ({ ...prev, session_idle_hours: Number(event.target.value) }))} />
                  <span className="block text-xs font-normal leading-5 text-zinc-500">После стольких часов без действий вход потребуется заново.</span>
                </label>
                <label className="block space-y-2 text-sm font-medium">
                  Общий срок входа, дней
                  <input type="number" min={1} max={365} className={field} value={platformDraft.session_absolute_days}
                    onChange={(event) => setPlatformDraft((prev) => ({ ...prev, session_absolute_days: Number(event.target.value) }))} />
                  <span className="block text-xs font-normal leading-5 text-zinc-500">Даже при активной работе сессия завершится по этому сроку.</span>
                </label>
                <label className="block space-y-2 text-sm font-medium">
                  Обновление входа, дней
                  <input type="number" min={1} max={365} className={field} value={platformDraft.session_refresh_days}
                    onChange={(event) => setPlatformDraft((prev) => ({ ...prev, session_refresh_days: Number(event.target.value) }))} />
                  <span className="block text-xs font-normal leading-5 text-zinc-500">Сколько браузер помнит вход, не спрашивая пароль снова.</span>
                </label>
              </div>
              <p className="mt-3 text-xs leading-5 text-zinc-500">Новые сроки действуют при следующем входе; уже открытые сессии завершатся по своим прежним правилам. Принудительно завершить все сессии можно в «Профиле».</p>

              <div className="mt-5 flex flex-wrap gap-2">
                <Button className={btn} onClick={() => void savePlatform()} disabled={savingPlatform || !platformValid}>
                  {savingPlatform ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}Сохранить
                </Button>
                <Button variant="outline" className={btn} onClick={() => void resetPlatform()} disabled={savingPlatform || !platform?.stored}>
                  <RefreshCw size={16} />Сбросить к серверу
                </Button>
              </div>

              <p className="mt-4 text-xs leading-5 text-zinc-500">
                Источник: {platform?.sources?.upload_max_bytes === "database" ? "сохранено в LMS" : "переменная окружения"}.
                Остальные параметры сервера (публичный адрес, CORS, доверенные прокси, очереди) задаются в <code className="rounded bg-zinc-100 px-1.5 py-0.5">.env</code>; их текущие значения и проверка — в разделе «Безопасность и доступ».
              </p>
            </section>

            <section id="security" className={`${card} scroll-mt-24`} aria-labelledby="security-title">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 rounded-xl bg-emerald-50 p-2 text-emerald-700"><ShieldCheck size={18} /></span>
                <div className="min-w-0">
                  <h2 id="security-title" className="text-lg font-semibold text-zinc-950">Безопасность и доступ</h2>
                  <p className="mt-1 text-sm leading-6 text-zinc-600">
                    Как сервер видит клиента за прокси: IP, HTTPS, куки и сроки сессии. Проверка ничего не меняет — только показывает фактические значения.
                  </p>
                </div>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="outline" className={btn} onClick={() => void loadSecurity()} disabled={loadingSecurity}>
                  {loadingSecurity ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}Проверить сейчас
                </Button>
              </div>

              {security ? (
                <div className="mt-5 space-y-4">
                  <ul className="space-y-2">
                    {security.checks.map((check) => (
                      <li key={check.key} className={`rounded-xl border px-4 py-3 text-sm ${check.ok ? "border-emerald-200 bg-emerald-50/60" : "border-amber-200 bg-amber-50/70"}`}>
                        <div className="flex items-start gap-2">
                          {check.ok ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-emerald-600" /> : <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-600" />}
                          <div className="min-w-0">
                            <p className={`font-medium ${check.ok ? "text-emerald-900" : "text-amber-900"}`}>{check.title}</p>
                            <p className={`mt-0.5 text-xs leading-5 ${check.ok ? "text-emerald-800/80" : "text-amber-900/80"}`}>{check.detail}</p>
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>

                  <dl className="grid gap-3 text-sm sm:grid-cols-2">
                    {[
                      ["IP клиента", security.client.ip || "не определён"],
                      ["Адрес прокси", security.client.peer || "—"],
                      ["Источник адреса", security.client.source === "direct" ? "прямое соединение" : security.client.source],
                      ["Доверенные сети", security.proxy.trusted_ranges.length ? security.proxy.trusted_ranges.join(", ") : "не заданы (TRUSTED_PROXY_IPS пуст)"],
                      ["Адрес сайта", `${security.request.protocol}://${security.request.host || "—"}`],
                      ["Куки", `${security.cookies.access.name} · HttpOnly · SameSite=${security.cookies.access.same_site} · ${(security.cookies.access.effective_secure ?? security.cookies.access.secure) ? "Secure" : "без Secure (браузер сохранит и по HTTP)"}${security.cookies.access.domain ? ` · домен ${security.cookies.access.domain}` : ""}`],
                      ["Сроки сессии", `простой ${security.sessions.idle_hours} ч · всего ${security.sessions.absolute_days} дн. · обновление ${security.sessions.refresh_days} дн.`],
                      ["Активных сессий", security.sessions.tracked_sessions < 0 ? "Redis недоступен" : String(security.sessions.tracked_sessions)],
                    ].map(([label, value]) => (
                      <div key={label} className="rounded-xl border border-zinc-200 bg-white px-4 py-3">
                        <dt className="text-xs uppercase tracking-wide text-zinc-500">{label}</dt>
                        <dd className="mt-1 break-words text-sm text-zinc-900">{value}</dd>
                      </div>
                    ))}
                  </dl>

                  <p className="text-xs leading-5 text-zinc-500">
                    Сроки сессии меняются в разделе «Платформа». Доверенные прокси, домен куки и HTTPS задаются в <code className="rounded bg-zinc-100 px-1.5 py-0.5">.env</code> и применяются при перезапуске контейнеров.
                  </p>
                </div>
              ) : (
                <p className="mt-4 text-sm text-zinc-500">Нажмите «Проверить сейчас», чтобы увидеть фактические значения.</p>
              )}
            </section>

            <section id="system" className={`${card} scroll-mt-24`} aria-labelledby="system-title">
              <h2 id="system-title" className="text-lg font-semibold text-zinc-950">Сервер и схема данных</h2>
              <p className="mt-1 text-sm leading-6 text-zinc-600">Эти параметры задаются в <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs">.env</code> и применяются при перезапуске контейнеров.</p>
              <dl className="mt-4 grid gap-3 sm:grid-cols-2">
                {[
                  ["Окружение", overview?.app_env || "—"],
                  ["Публичный адрес", overview?.public_app_url || "—"],
                  ["Лимит файла (действующий)", overview ? `${Math.round(overview.upload_max_bytes / (1024 * 1024))} МБ` : "—"],
                  ["Хранилище S3", overview ? `${overview.s3_bucket || "—"}${overview.s3_endpoint ? ` · ${overview.s3_endpoint}` : ""}` : "—"],
                  ["Схема БД", overview ? `${overview.schema.current || "не определена"} / ожидается ${overview.schema.expected}` : "—"],
                  ["Браузерные копии файлов", overview?.media_dispatcher_enabled ? "включены" : "выключены"],
                  ["Фоновые воркеры", overview?.queue?.workers === null || overview?.queue?.workers === undefined ? "нет связи с Redis" : `${overview.queue.workers} · в очереди тестов ${overview.queue.regen_pending ?? 0}`],
                ].map(([label, value]) => (
                  <div key={String(label)} className="rounded-xl border border-zinc-200 px-4 py-3">
                    <dt className="text-xs uppercase tracking-wide text-zinc-500">{label}</dt>
                    <dd className="mt-1 break-words text-sm font-medium text-zinc-900">{String(value)}</dd>
                  </div>
                ))}
              </dl>
              <div className="mt-4 rounded-xl border border-zinc-200 px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-xs uppercase tracking-wide text-zinc-500">Состояние сервисов</p>
                    <p className={`mt-1 text-sm font-medium ${health ? (health.ok ? "text-emerald-700" : "text-rose-700") : "text-zinc-600"}`}>
                      {checkingHealth ? "Проверяем…" : health ? health.message : "Ещё не проверяли"}
                      {health && !checkingHealth ? <span className="ml-2 text-xs font-normal text-zinc-400">{health.at}</span> : null}
                    </p>
                  </div>
                  <Button variant="outline" className={btn} disabled={checkingHealth} onClick={() => void checkHealth()}>
                    {checkingHealth ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}Проверить
                  </Button>
                </div>
                <p className="mt-2 text-xs leading-5 text-zinc-500">
                  Проверяются база данных, Redis и хранилище S3. Обновление схемы: <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs">alembic upgrade head</code>.
                </p>
              </div>
            </section>

            <section id="errors" className={`${card} scroll-mt-24`} aria-labelledby="errors-title">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 rounded-xl bg-rose-50 p-2 text-rose-700"><AlertTriangle size={18} /></span>
                  <div>
                    <h2 id="errors-title" className="text-lg font-semibold text-zinc-950">Ошибки сервера</h2>
                    <p className="mt-1 text-sm leading-6 text-zinc-600">
                      Последние ответы 5xx с местом падения. Код из сообщения «Код для поддержки» совпадает с полем{" "}
                      <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs">Код</code> ниже — по нему видно, что именно сломалось.
                    </p>
                  </div>
                </div>
                <Button variant="outline" className={btn} disabled={loadingErrors} onClick={() => void loadErrors()}>
                  {loadingErrors ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}Обновить
                </Button>
              </div>

              {!serverErrors || serverErrors.items.length === 0 ? (
                <p role="status" className="mt-4 flex items-center gap-2 rounded-xl border border-zinc-200 px-4 py-3 text-sm text-zinc-600">
                  <CheckCircle2 size={16} className="text-emerald-600" />
                  {loadingErrors ? "Читаем журнал…" : serverErrors?.hint || "Серверных ошибок не зафиксировано."}
                </p>
              ) : (
                <ul className="mt-4 space-y-3">
                  {serverErrors.items.map((item) => (
                    <li key={`${item.rid}-${item.ts}`} className="rounded-xl border border-zinc-200 px-4 py-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-sm font-medium text-zinc-900">
                          <span className="rounded bg-rose-50 px-1.5 py-0.5 font-mono text-xs text-rose-700">{item.status}</span>{" "}
                          <span className="font-mono text-xs text-zinc-700">{item.method} {item.path}</span>
                        </p>
                        <span className="text-xs text-zinc-500">{new Date(item.ts).toLocaleString("ru-RU")}</span>
                      </div>
                      <p className="mt-2 break-all font-mono text-xs text-zinc-500">Код: {item.rid}</p>
                      {item.error ? <p className="mt-1 break-words text-sm text-rose-800">{item.error}</p> : null}
                      {item.traceback ? (
                        <details className="mt-2">
                          <summary className="cursor-pointer text-xs font-medium text-zinc-600">Где именно упало</summary>
                          <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-zinc-950 p-3 text-[11px] leading-5 text-zinc-100">{item.traceback}</pre>
                        </details>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
              {serverErrors?.log_file ? (
                <p className="mt-3 break-all text-xs text-zinc-400">Журнал: {serverErrors.log_file}</p>
              ) : null}
            </section>
          </div>
        )}
      </div>
    </AppShell>
  );
}
