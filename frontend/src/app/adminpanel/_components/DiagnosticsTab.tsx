"use client";

import { Button } from "@/components/ui/button";
import { useMemo, useState } from "react";

interface DiagnosticsTabProps {
  sys: any;
  sysLoading: boolean;
  loadSystemStatus: () => Promise<void>;
  runtimeLlmOverridesAllowed: boolean;
  openrouterEnabledDraft: boolean;
  setOpenrouterEnabledDraft: (val: boolean) => void;
  openrouterBaseUrlDraft: string;
  setOpenrouterBaseUrlDraft: (val: string) => void;
  openrouterModelDraft: string;
  setOpenrouterModelDraft: (val: string) => void;
  openrouterApiKeyDraft: string;
  setOpenrouterApiKeyDraft: (val: string) => void;
  openrouterApiKeyMasked: string;
  openrouterHttpRefererDraft: string;
  setOpenrouterHttpRefererDraft: (val: string) => void;
  openrouterAppTitleDraft: string;
  setOpenrouterAppTitleDraft: (val: string) => void;
  llmEffective: any;
  diagSaving: boolean;
  saveRuntimeLlmSettings: () => Promise<void>;
  loadRuntimeLlmSettings: () => Promise<void>;
  resetRuntimeLlmSettings: () => Promise<void>;

  s3Draft: {
    s3_endpoint_url: string;
    s3_public_endpoint_url: string;
    s3_access_key_id: string;
    s3_secret_access_key: string;
    s3_bucket: string;
    s3_region_name: string;
    s3_addressing_style: string;
    s3_access_key_id_masked: string;
    s3_secret_access_key_masked: string;
  };
  setS3Draft: (next: any) => void;
  saveRuntimeS3Settings: () => Promise<void>;
  loadRuntimeS3Settings: () => Promise<void>;
  resetRuntimeS3Settings: () => Promise<void>;

  brokenModulesBusy: boolean;
  brokenModules: { id: string; title: string }[];
  brokenModulesCount: number;
  scanBrokenModules: () => Promise<void>;
  purgeBrokenModules: () => Promise<void>;

  modulesStorageScanBusy: boolean;
  modulesStorageScan: any[];
  scanModulesStorage: () => Promise<void>;
}

export function DiagnosticsTab(props: DiagnosticsTabProps) {
  const {
    sys,
    sysLoading,
    loadSystemStatus,
    runtimeLlmOverridesAllowed,
    openrouterEnabledDraft,
    setOpenrouterEnabledDraft,
    openrouterBaseUrlDraft,
    setOpenrouterBaseUrlDraft,
    openrouterModelDraft,
    setOpenrouterModelDraft,
    openrouterApiKeyDraft,
    setOpenrouterApiKeyDraft,
    openrouterApiKeyMasked,
    openrouterHttpRefererDraft,
    setOpenrouterHttpRefererDraft,
    openrouterAppTitleDraft,
    setOpenrouterAppTitleDraft,
    llmEffective,
    diagSaving,
    saveRuntimeLlmSettings,
    loadRuntimeLlmSettings,
    resetRuntimeLlmSettings,
    brokenModulesBusy,
    brokenModules,
    brokenModulesCount,
    scanBrokenModules,
    purgeBrokenModules,

    modulesStorageScanBusy,
    modulesStorageScan,
    scanModulesStorage,

    s3Draft,
    setS3Draft,
    saveRuntimeS3Settings,
    loadRuntimeS3Settings,
    resetRuntimeS3Settings,
  } = props;

  const [storageProblemsOnly, setStorageProblemsOnly] = useState(true);

  const storageRows = useMemo(() => {
    const xs = Array.isArray(modulesStorageScan) ? modulesStorageScan : [];
    if (!storageProblemsOnly) return xs;
    return xs.filter((it: any) => {
      const warns = Array.isArray(it?.warnings) ? it.warnings : [];
      const w = new Set<string>(warns.map((x: any) => String(x || "").trim()).filter(Boolean));
      const bad =
        w.has("STORAGE_EMPTY") ||
        w.has("S3_THEORY_BUT_NO_QUIZ") ||
        w.has("QUIZ_LESSON_TEXT_SHORT") ||
        Number(it?.db_suspicious_quiz_lessons || 0) > 0;
      return bad;
    });
  }, [modulesStorageScan, storageProblemsOnly]);

  const instance = (sys as any)?.instance || {};
  const cfg = (sys as any)?.config || {};

  return (
    <div className="mt-8 space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-6">
        <div>
          <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900]">ЦЕНТР УПРАВЛЕНИЯ</div>
          <div className="mt-2 text-2xl font-black tracking-tighter text-zinc-950 uppercase">Диагностика</div>
          <div className="mt-2 text-[10px] font-bold text-zinc-600 uppercase tracking-widest">Статусы, runtime-настройки и проверки целостности</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
            disabled={sysLoading}
            onClick={() => void loadSystemStatus()}
          >
            {sysLoading ? "..." : "ОБНОВИТЬ СТАТУС"}
          </Button>
          <Button
            variant="outline"
            className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
            disabled={diagSaving}
            onClick={() => void Promise.all([loadRuntimeLlmSettings(), loadRuntimeS3Settings()])}
          >
            ОБНОВИТЬ RUNTIME
          </Button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-12 items-start">
        <div className="lg:col-span-12 rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-8 shadow-xl">
          <div className="flex items-end justify-between gap-6">
            <div>
              <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">СИСТЕМА</div>
              <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">СТАТУС</div>
            </div>
          </div>

          <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {(
              [
                { key: "db", label: "DB" },
                { key: "redis", label: "REDIS" },
                { key: "rq", label: "RQ" },
                { key: "s3", label: "S3" },
                { key: "openrouter", label: "OPENROUTER" },
              ] as { key: string; label: string }[]
            ).map((x) => {
              const ok = !!(sys as any)?.[x.key]?.ok;
              return (
                <div key={x.key} className="rounded-2xl border border-zinc-200 bg-white p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">{x.label}</div>
                    <div
                      className={
                        "inline-flex items-center rounded-full border px-3 py-1 text-[9px] font-black uppercase tracking-widest " +
                        (ok
                          ? "border-[#284e13]/20 bg-[#284e13]/10 text-[#284e13]"
                          : "border-rose-200 bg-rose-50 text-rose-800")
                      }
                    >
                      {ok ? "OK" : "FAIL"}
                    </div>
                  </div>

                  {x.key === "rq" && (sys as any)?.rq ? (
                    <div className="mt-2 text-[10px] font-bold text-zinc-600 uppercase tracking-widest">
                      w: {Number((sys as any)?.rq?.workers || 0)} · q: {Number((sys as any)?.rq?.queued || 0)}
                      {typeof (sys as any)?.rq?.started === "number" ? ` · s: ${Number((sys as any)?.rq?.started || 0)}` : ""}
                      {typeof (sys as any)?.rq?.scheduled === "number" ? ` · sch: ${Number((sys as any)?.rq?.scheduled || 0)}` : ""}
                      {typeof (sys as any)?.rq?.deferred === "number" ? ` · d: ${Number((sys as any)?.rq?.deferred || 0)}` : ""}
                      {typeof (sys as any)?.rq?.failed === "number" ? ` · f: ${Number((sys as any)?.rq?.failed || 0)}` : ""}
                    </div>
                  ) : null}
                  {x.key === "openrouter" && (sys as any)?.openrouter ? (
                    <div className="mt-2 text-[10px] font-bold text-zinc-600 uppercase tracking-widest break-words">
                      {String((sys as any)?.openrouter?.base_url || "")} · {String((sys as any)?.openrouter?.model || "")}
                      {String((sys as any)?.openrouter?.reason || "").trim() ? ` · ${String((sys as any)?.openrouter?.reason || "")}` : ""}
                    </div>
                  ) : null}
                  {x.key === "s3" && (sys as any)?.s3 && String((sys as any)?.s3?.reason || "").trim() ? (
                    <div className="mt-2 text-[10px] font-bold text-rose-700 uppercase tracking-widest break-words">
                      {String((sys as any)?.s3?.reason || "")}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>

        <div className="lg:col-span-12 rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-0 shadow-xl overflow-hidden">
          <details open>
            <summary className="cursor-pointer select-none px-8 py-6">
              <div className="flex items-center justify-between gap-6">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">INSTANCE / CONFIG</div>
                  <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">ПАСПОРТ</div>
                </div>
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-600">свернуть/развернуть</div>
              </div>
            </summary>
            <div className="px-8 pb-8">
              <div className="grid gap-6 lg:grid-cols-12 items-start">
                <div className="lg:col-span-6 rounded-[32px] border border-zinc-200 bg-white p-8">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">INSTANCE</div>
                    <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">ПАСПОРТ</div>
                    <div className="mt-2 text-[10px] font-bold text-zinc-600 uppercase tracking-widest">Без секретов. Для быстрой проверки прод-конфига.</div>
                  </div>
                  <div className="mt-6 grid gap-3">
                    <div className="grid grid-cols-12 gap-3">
                      <div className="col-span-4 text-[10px] font-black uppercase tracking-widest text-zinc-500">APP_ENV</div>
                      <div className="col-span-8 font-mono text-[12px] text-zinc-900 break-all">{String(instance.app_env || "") || "—"}</div>
                    </div>
                    <div className="grid grid-cols-12 gap-3">
                      <div className="col-span-4 text-[10px] font-black uppercase tracking-widest text-zinc-500">HOSTNAME</div>
                      <div className="col-span-8 font-mono text-[12px] text-zinc-900 break-all">{String(instance.hostname || "") || "—"}</div>
                    </div>
                    <div className="grid grid-cols-12 gap-3">
                      <div className="col-span-4 text-[10px] font-black uppercase tracking-widest text-zinc-500">TIME (UTC)</div>
                      <div className="col-span-8 font-mono text-[12px] text-zinc-900 break-all">{String(instance.time_utc || "") || "—"}</div>
                    </div>
                    <div className="grid grid-cols-12 gap-3">
                      <div className="col-span-4 text-[10px] font-black uppercase tracking-widest text-zinc-500">PUBLIC_APP_URL</div>
                      <div className="col-span-8 font-mono text-[12px] text-zinc-900 break-all">{String(instance.public_app_url || "") || "—"}</div>
                    </div>
                    <div className="grid grid-cols-12 gap-3">
                      <div className="col-span-4 text-[10px] font-black uppercase tracking-widest text-zinc-500">CORS</div>
                      <div className="col-span-8 font-mono text-[12px] text-zinc-900 break-all">{String(instance.cors_allow_origins || "") || "—"}</div>
                    </div>
                  </div>
                </div>

                <div className="lg:col-span-6 rounded-[32px] border border-zinc-200 bg-white p-8">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">CONFIG</div>
                    <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">EFFECTIVE (SAFE)</div>
                    <div className="mt-2 text-[10px] font-bold text-zinc-600 uppercase tracking-widest">Очереди, лимиты, таймауты. Без ключей.</div>
                  </div>
                  <div className="mt-6 grid gap-3">
                    <div className="grid grid-cols-12 gap-3">
                      <div className="col-span-5 text-[10px] font-black uppercase tracking-widest text-zinc-500">RQ QUEUES</div>
                      <div className="col-span-7 font-mono text-[12px] text-zinc-900 break-all">
                        {String((cfg as any)?.rq?.queue_import || "") || "—"} / {String((cfg as any)?.rq?.queue_regen || "") || "—"}
                      </div>
                    </div>
                    <div className="grid grid-cols-12 gap-3">
                      <div className="col-span-5 text-[10px] font-black uppercase tracking-widest text-zinc-500">ZIP LIMITS</div>
                      <div className="col-span-7 font-mono text-[12px] text-zinc-900 break-all">
                        files={String((cfg as any)?.import_zip?.max_files ?? "")} entry={String((cfg as any)?.import_zip?.max_entry_bytes ?? "")} total={String((cfg as any)?.import_zip?.max_uncompressed_bytes ?? "")}
                      </div>
                    </div>
                    <div className="grid grid-cols-12 gap-3">
                      <div className="col-span-5 text-[10px] font-black uppercase tracking-widest text-zinc-500">S3 TIMEOUTS</div>
                      <div className="col-span-7 font-mono text-[12px] text-zinc-900 break-all">
                        c={String((cfg as any)?.s3?.connect_timeout_seconds ?? "")} r={String((cfg as any)?.s3?.read_timeout_seconds ?? "")} attempts={String((cfg as any)?.s3?.max_attempts ?? "")}
                      </div>
                    </div>
                    <div className="grid grid-cols-12 gap-3">
                      <div className="col-span-5 text-[10px] font-black uppercase tracking-widest text-zinc-500">OPENROUTER</div>
                      <div className="col-span-7 font-mono text-[12px] text-zinc-900 break-all">
                        {String((cfg as any)?.llm?.openrouter?.base_url || "") || "—"} | {String((cfg as any)?.llm?.openrouter?.model || "") || "—"}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </details>
        </div>

        <div className="lg:col-span-12 rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-0 shadow-xl overflow-hidden">
          <details open>
            <summary className="cursor-pointer select-none px-8 py-6">
              <div className="flex items-center justify-between gap-6">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">RUNTIME</div>
                  <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">OPENROUTER / LLM</div>
                </div>
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-600">свернуть/развернуть</div>
              </div>
            </summary>
            <div className="px-8 pb-8">
              <div className="grid gap-4 max-w-3xl">
                <div className="grid gap-3 rounded-2xl border border-zinc-200 bg-white p-5">
                  <label className="flex items-center justify-between gap-4">
                    <div className="text-[11px] font-bold text-zinc-800">ВКЛЮЧЕНО</div>
                    <input
                      type="checkbox"
                      checked={openrouterEnabledDraft}
                      onChange={(e) => setOpenrouterEnabledDraft(e.target.checked)}
                      className="h-5 w-5"
                    />
                  </label>
                  <div className="grid gap-2">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">BASE URL</div>
                    <input
                      value={openrouterBaseUrlDraft}
                      onChange={(e) => setOpenrouterBaseUrlDraft(e.target.value)}
                      placeholder="https://openrouter.ai/api/v1"
                      className="h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
                    />
                  </div>
                  <div className="grid gap-2">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">MODEL</div>
                    <input
                      value={openrouterModelDraft}
                      onChange={(e) => setOpenrouterModelDraft(e.target.value)}
                      placeholder="openai/gpt-4o-mini"
                      className="h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
                    />
                  </div>
                  <div className="grid gap-2">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">API KEY</div>
                    <input
                      value={openrouterApiKeyDraft}
                      onChange={(e) => setOpenrouterApiKeyDraft(e.target.value)}
                      placeholder={openrouterApiKeyMasked ? `СЕЙЧАС: ${openrouterApiKeyMasked}` : "sk-or-v1..."}
                      className="h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
                    />
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">
                      хранится в Redis (runtime), не в .env
                    </div>
                  </div>
                  <div className="grid gap-2">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">HTTP REFERER</div>
                    <input
                      value={openrouterHttpRefererDraft}
                      onChange={(e) => setOpenrouterHttpRefererDraft(e.target.value)}
                      placeholder="https://your-app"
                      className="h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
                    />
                  </div>
                  <div className="grid gap-2">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">APP TITLE</div>
                    <input
                      value={openrouterAppTitleDraft}
                      onChange={(e) => setOpenrouterAppTitleDraft(e.target.value)}
                      placeholder="CoreLMS"
                      className="h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
                    />
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="primary"
                    className="h-11 rounded-2xl font-black uppercase tracking-widest text-[9px]"
                    disabled={diagSaving || !runtimeLlmOverridesAllowed}
                    onClick={() => void saveRuntimeLlmSettings()}
                  >
                    {diagSaving ? "..." : "СОХРАНИТЬ"}
                  </Button>
                  <Button
                    variant="outline"
                    className="h-11 rounded-2xl font-black uppercase tracking-widest text-[9px]"
                    disabled={diagSaving || !runtimeLlmOverridesAllowed}
                    onClick={() => void resetRuntimeLlmSettings()}
                  >
                    СБРОСИТЬ RUNTIME
                  </Button>
                  <Button
                    variant="outline"
                    className="h-11 rounded-2xl font-black uppercase tracking-widest text-[9px]"
                    disabled={diagSaving}
                    onClick={() => void loadRuntimeLlmSettings()}
                  >
                    ОБНОВИТЬ
                  </Button>
                </div>
              </div>
            </div>
          </details>
        </div>

        <div className="lg:col-span-12 rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-0 shadow-xl overflow-hidden">
          <details open>
            <summary className="cursor-pointer select-none px-8 py-6">
              <div className="flex items-center justify-between gap-6">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">RUNTIME</div>
                  <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">S3</div>
                  <div className="mt-2 text-[10px] font-bold text-zinc-600 uppercase tracking-widest">Для prod используем внешний S3 (REG.RU).</div>
                </div>
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-600">свернуть/развернуть</div>
              </div>
            </summary>

            <div className="px-8 pb-8">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  disabled={diagSaving}
                  onClick={() => void loadRuntimeS3Settings()}
                >
                  ОБНОВИТЬ
                </Button>
                <Button
                  variant="outline"
                  className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  disabled={diagSaving}
                  onClick={() => void resetRuntimeS3Settings()}
                >
                  СБРОСИТЬ RUNTIME
                </Button>
                <Button
                  variant="primary"
                  className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  disabled={diagSaving}
                  onClick={() => void saveRuntimeS3Settings()}
                >
                  СОХРАНИТЬ
                </Button>
                <Button
                  variant="outline"
                  className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  disabled={sysLoading}
                  onClick={() => void loadSystemStatus()}
                >
                  {sysLoading ? "..." : "ПРОВЕРИТЬ"}
                </Button>
              </div>

              <div className="mt-6 grid gap-4 lg:grid-cols-2">
            <div className="grid gap-3 rounded-2xl border border-zinc-200 bg-white p-5">
              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ENDPOINT URL</div>
              <input
                value={String(s3Draft?.s3_endpoint_url || "")}
                onChange={(e) => setS3Draft({ ...s3Draft, s3_endpoint_url: e.target.value })}
                placeholder="https://s3.regru.cloud"
                className="h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
              />

              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">PUBLIC ENDPOINT URL</div>
              <input
                value={String(s3Draft?.s3_public_endpoint_url || "")}
                onChange={(e) => setS3Draft({ ...s3Draft, s3_public_endpoint_url: e.target.value })}
                placeholder="https://s3.regru.cloud"
                className="h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
              />

              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">BUCKET</div>
              <input
                value={String(s3Draft?.s3_bucket || "")}
                onChange={(e) => setS3Draft({ ...s3Draft, s3_bucket: e.target.value })}
                placeholder="corelms-content"
                className="h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
              />
            </div>

            <div className="grid gap-3 rounded-2xl border border-zinc-200 bg-white p-5">
              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ACCESS KEY ID</div>
              <input
                value={String(s3Draft?.s3_access_key_id || "")}
                onChange={(e) => setS3Draft({ ...s3Draft, s3_access_key_id: e.target.value })}
                placeholder={String(s3Draft?.s3_access_key_id_masked || "") ? `СЕЙЧАС: ${String(s3Draft.s3_access_key_id_masked)}` : ""}
                className="h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
              />

              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">SECRET ACCESS KEY</div>
              <input
                value={String(s3Draft?.s3_secret_access_key || "")}
                onChange={(e) => setS3Draft({ ...s3Draft, s3_secret_access_key: e.target.value })}
                placeholder={String(s3Draft?.s3_secret_access_key_masked || "") ? `СЕЙЧАС: ${String(s3Draft.s3_secret_access_key_masked)}` : ""}
                className="h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
              />

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">REGION</div>
                  <input
                    value={String(s3Draft?.s3_region_name || "")}
                    onChange={(e) => setS3Draft({ ...s3Draft, s3_region_name: e.target.value })}
                    placeholder="us-east-1"
                    className="h-11 w-full rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
                  />
                </div>
                <div>
                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ADDRESSING</div>
                  <input
                    value={String(s3Draft?.s3_addressing_style || "")}
                    onChange={(e) => setS3Draft({ ...s3Draft, s3_addressing_style: e.target.value })}
                    placeholder="path"
                    className="h-11 w-full rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-bold text-zinc-900"
                  />
                </div>
              </div>
              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">
                хранится в Redis (runtime), не в .env
              </div>
            </div>
          </div>
            </div>
          </details>
        </div>

        <div className="lg:col-span-12 rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-0 shadow-xl overflow-hidden">
          <details open>
            <summary className="cursor-pointer select-none px-8 py-6">
              <div className="flex items-center justify-between gap-6">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">MAINTENANCE</div>
                  <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">Согласованность S3/DB</div>
                  <div className="mt-2 text-[10px] font-bold text-zinc-600 uppercase tracking-widest">
                    Битые модули (нет объектов в S3): {Number(brokenModulesCount || 0)}
                  </div>
                </div>
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-600">свернуть/развернуть</div>
              </div>
            </summary>

            <div className="px-8 pb-8">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  disabled={brokenModulesBusy}
                  onClick={() => void scanBrokenModules()}
                >
                  {brokenModulesBusy ? "..." : "СКАН"}
                </Button>
                <Button
                  variant="destructive"
                  className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  disabled={brokenModulesBusy || Number(brokenModulesCount || 0) <= 0}
                  onClick={() => void purgeBrokenModules()}
                >
                  УДАЛИТЬ ИЗ DB
                </Button>
              </div>

              {Array.isArray(brokenModules) && brokenModules.length ? (
                <div className="mt-6 grid gap-2">
                  {brokenModules.slice(0, 12).map((m) => (
                    <div key={m.id} className="rounded-2xl border border-zinc-200 bg-white px-4 py-3">
                      <div className="text-[11px] font-black uppercase tracking-tight text-zinc-950 truncate">{m.title}</div>
                      <div className="mt-1 text-[10px] font-bold text-zinc-500 truncate">{m.id}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-6 text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Нет данных (нажми СКАН)</div>
              )}
            </div>
          </details>
        </div>

        <div className="lg:col-span-12 rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-0 shadow-xl overflow-hidden">
          <details>
            <summary className="cursor-pointer select-none px-8 py-6">
              <div className="flex items-center justify-between gap-6">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">МОДУЛИ</div>
                  <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">СКАН STORAGE</div>
                </div>
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-600">свернуть/развернуть</div>
              </div>
            </summary>

            <div className="px-8 pb-8">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className={
                    "h-10 rounded-xl border px-4 text-[9px] font-black uppercase tracking-widest " +
                    (storageProblemsOnly
                      ? "border-[#fe9900]/25 bg-[#fe9900]/10 text-[#fe9900]"
                      : "border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50")
                  }
                  onClick={() => setStorageProblemsOnly((v) => !v)}
                >
                  {storageProblemsOnly ? "ТОЛЬКО ПРОБЛЕМЫ" : "ВСЕ"}
                </button>
                <Button
                  variant="outline"
                  className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  disabled={modulesStorageScanBusy}
                  onClick={() => void scanModulesStorage()}
                >
                  {modulesStorageScanBusy ? "..." : "СКАНИРОВАТЬ"}
                </Button>
              </div>

              <div className="mt-6">
                {!Array.isArray(modulesStorageScan) || modulesStorageScan.length === 0 ? (
                  <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">НЕТ ДАННЫХ</div>
                ) : storageProblemsOnly && storageRows.length === 0 ? (
                  <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">ПРОБЛЕМ НЕ НАЙДЕНО</div>
                ) : (
                  <div className="grid gap-2 max-h-[520px] overflow-auto pr-2">
                    {(storageRows || []).map((it: any) => {
                      const warns = Array.isArray(it?.warnings) ? it.warnings : [];
                      const w = new Set<string>(warns.map((x: any) => String(x || "").trim()).filter(Boolean));
                      const bad = w.has("STORAGE_EMPTY") || w.has("QUIZ_LESSON_TEXT_SHORT");
                      return (
                        <div
                          key={String(it?.module_id || Math.random())}
                          className={
                            "rounded-2xl border p-4 " +
                            (bad ? "border-rose-200 bg-rose-50/40" : "border-zinc-200 bg-white")
                          }
                        >
                          <div className="flex items-start justify-between gap-4">
                            <div className="min-w-0">
                              <div className="truncate text-[11px] font-black uppercase tracking-widest text-zinc-950">
                                {String(it?.module_title || "") || String(it?.module_id || "")}
                              </div>
                              <div className="mt-1 truncate text-[10px] font-bold text-zinc-600 font-mono">
                                {String(it?.storage_prefix || "")}
                              </div>
                            </div>
                            <div className="shrink-0 flex flex-wrap items-center gap-2">
                              <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                DB: {Number(it?.db_submodules || 0)}
                              </div>
                              <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                QUIZ: {Number(it?.db_quiz_lessons || 0)}
                              </div>
                              <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                FILE: {Number(it?.db_file_lessons || 0)}
                              </div>
                              {Number(it?.db_suspicious_quiz_lessons || 0) > 0 ? (
                                <div className="rounded-full border border-rose-200 bg-rose-50 px-2.5 py-1 text-[9px] font-black uppercase tracking-widest text-rose-800">
                                  SHORT: {Number(it?.db_suspicious_quiz_lessons || 0)}
                                </div>
                              ) : null}
                              {w.size ? (
                                <div className="rounded-full border border-zinc-200 bg-white px-2.5 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                  WARN: {Array.from(w).slice(0, 3).join(" · ")}
                                </div>
                              ) : null}
                            </div>
                          </div>

                          {Array.isArray(it?.s3_sample_keys) && it.s3_sample_keys.length ? (
                            <div className="mt-3 rounded-xl border border-zinc-200 bg-zinc-50 p-3">
                              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">S3 SAMPLE</div>
                              <div className="mt-2 grid gap-1">
                                {(it.s3_sample_keys as any[]).slice(0, 12).map((k, idx) => (
                                  <div key={idx} className="font-mono text-[10px] text-zinc-700 break-all">
                                    {String(k)}
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : (
                            <div className="mt-3 text-[10px] font-bold text-zinc-600">S3: ПУСТО</div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          </details>
        </div>
      </div>
    </div>
  );
}
