"use client";

import { Button } from "@/components/ui/button";
import { useMemo, useState } from "react";

interface DiagnosticsTabProps {
  sys: any;
  sysLoading: boolean;
  loadSystemStatus: () => Promise<void>;
  llmOrderDraft: string;
  setLlmOrderDraft: (val: string) => void;
  ollamaEnabledDraft: boolean;
  setOllamaEnabledDraft: (val: boolean) => void;
  ollamaBaseUrlDraft: string;
  setOllamaBaseUrlDraft: (val: string) => void;
  ollamaModelDraft: string;
  setOllamaModelDraft: (val: string) => void;
  hfEnabledDraft: boolean;
  setHfEnabledDraft: (val: boolean) => void;
  hfBaseUrlDraft: string;
  setHfBaseUrlDraft: (val: string) => void;
  hfModelDraft: string;
  setHfModelDraft: (val: string) => void;
  hfTokenDraft: string;
  setHfTokenDraft: (val: string) => void;
  hfTokenMasked: string;
  llmEffective: any;
  diagSaving: boolean;
  clearRuntimeHfToken: () => Promise<void>;
  saveRuntimeLlmSettings: () => Promise<void>;
  loadRuntimeLlmSettings: () => Promise<void>;

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
    llmOrderDraft,
    setLlmOrderDraft,
    ollamaEnabledDraft,
    setOllamaEnabledDraft,
    ollamaBaseUrlDraft,
    setOllamaBaseUrlDraft,
    ollamaModelDraft,
    setOllamaModelDraft,
    hfEnabledDraft,
    setHfEnabledDraft,
    hfBaseUrlDraft,
    setHfBaseUrlDraft,
    hfModelDraft,
    setHfModelDraft,
    hfTokenDraft,
    setHfTokenDraft,
    hfTokenMasked,
    llmEffective,
    diagSaving,
    clearRuntimeHfToken,
    saveRuntimeLlmSettings,
    brokenModulesBusy,
    brokenModules,
    brokenModulesCount,
    scanBrokenModules,
    purgeBrokenModules,

    modulesStorageScanBusy,
    modulesStorageScan,
    scanModulesStorage,
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

  return (
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
                      {typeof (sys as any)?.rq?.started === "number" ? ` · started: ${Number((sys as any)?.rq?.started || 0)}` : ""}
                      {typeof (sys as any)?.rq?.scheduled === "number" ? ` · scheduled: ${Number((sys as any)?.rq?.scheduled || 0)}` : ""}
                      {typeof (sys as any)?.rq?.deferred === "number" ? ` · deferred: ${Number((sys as any)?.rq?.deferred || 0)}` : ""}
                      {typeof (sys as any)?.rq?.failed === "number" ? ` · failed: ${Number((sys as any)?.rq?.failed || 0)}` : ""}
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

        <div className="lg:col-span-12 rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-8 shadow-xl">
          <div className="flex items-end justify-between gap-6">
            <div>
              <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">MAINTENANCE</div>
              <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">Согласованность S3/DB</div>
              <div className="mt-2 text-[10px] font-bold text-zinc-600 uppercase tracking-widest">
                Битые модули (нет объектов в S3): {Number(brokenModulesCount || 0)}
              </div>
            </div>
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

        <div className="lg:col-span-12 rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-8 shadow-xl">
          <div className="flex items-end justify-between gap-6">
            <div>
              <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">МОДУЛИ</div>
              <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">СКАН STORAGE</div>
            </div>
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
      </div>
    </div>
  );
}
