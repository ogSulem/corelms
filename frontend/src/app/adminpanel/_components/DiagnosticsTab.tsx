"use client";

import { Button } from "@/components/ui/button";
import { useMemo, useState } from "react";

interface DiagnosticsTabProps {
  sys: any;
  sysLoading: boolean;
  loadSystemStatus: (probe?: boolean) => Promise<void>;
  probeStatus: () => Promise<void>;


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
    probeStatus,
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

  const instance = (sys as any)?.instance || {};
  const cfg = (sys as any)?.config || {};

  return (
    <div className="mt-8 space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-6">
        <div>
          <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900]">ЦЕНТР УПРАВЛЕНИЯ</div>
          <div className="mt-2 text-2xl font-black tracking-tighter text-zinc-950 uppercase">Диагностика</div>
          <div className="mt-2 text-[10px] font-bold text-zinc-600 uppercase tracking-widest">Состояние сервисов и проверки целостности данных</div>
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
              const item = (sys as any)?.[x.key];
              const ok = !!item?.ok;
              // Внешние сервисы проверяются по кнопке, поэтому «не проверено» — это не ошибка.
              const configured = item?.configured === undefined ? true : !!item?.configured;
              const probed = item?.probed === undefined ? true : !!item?.probed;
              const state = !configured ? "настроить" : !probed ? "не проверено" : ok ? "ok" : "fail";
              return (
                <div key={x.key} className="rounded-2xl border border-zinc-200 bg-white p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">{x.label}</div>
                    <div
                      className={
                        "inline-flex items-center rounded-full border px-3 py-1 text-[9px] font-black uppercase tracking-widest " +
                        (state === "ok"
                          ? "border-[#284e13]/20 bg-[#284e13]/10 text-[#284e13]"
                          : state === "fail"
                            ? "border-rose-200 bg-rose-50 text-rose-800"
                            : "border-zinc-200 bg-zinc-50 text-zinc-600")
                      }
                    >
                      {state === "ok" ? "OK" : state === "fail" ? "FAIL" : state === "настроить" ? "НЕ НАСТРОЕНО" : "НЕ ПРОВЕРЕНО"}
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
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">ИНТЕГРАЦИИ</div>
                  <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">AI И ХРАНИЛИЩЕ</div>
                </div>
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-600">свернуть/развернуть</div>
              </div>
            </summary>
            <div className="px-8 pb-8">
              <p className="text-xs font-bold text-zinc-600">
                Изменение токенов, модели и хранилища — в одном месте: Админ-центр → Настройки. Здесь только состояние.
              </p>
              <div className="mt-5 grid gap-3 lg:grid-cols-2">
                <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">AI ДЛЯ ТЕСТОВ</div>
                  <div className="mt-2 text-[11px] font-black uppercase tracking-wide text-zinc-950">
                    {!(sys as any)?.openrouter?.configured
                      ? "НЕ НАСТРОЕН"
                      : !(sys as any)?.openrouter?.probed
                        ? "НАСТРОЕН, НЕ ПРОВЕРЕН"
                        : (sys as any)?.openrouter?.ok
                          ? "ПОДКЛЮЧЕНИЕ РАБОТАЕТ"
                          : "ПРОВЕРКА НЕ ПРОШЛА"}
                  </div>
                  <div className="mt-2 break-all text-[10px] font-bold text-zinc-600">
                    {String((sys as any)?.openrouter?.model || "—")} · {String((sys as any)?.openrouter?.base_url || "—")}
                  </div>
                  {(sys as any)?.openrouter?.reason ? (
                    <div className="mt-1 break-all text-[10px] font-bold text-rose-700">{String((sys as any)?.openrouter?.reason)}</div>
                  ) : null}
                  <div className="mt-3 flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      className="text-[10px] font-black uppercase tracking-widest text-zinc-700 underline disabled:opacity-50"
                      disabled={sysLoading || !(sys as any)?.openrouter?.configured}
                      onClick={() => void probeStatus()}
                    >
                      {sysLoading ? "Проверяем…" : (sys as any)?.openrouter?.probed ? "Проверить снова" : "Проверить подключение"}
                    </button>
                    <a href="/admin/settings#ai" className="text-[10px] font-black uppercase tracking-widest text-amber-700 underline">
                      Настроить AI →
                    </a>
                  </div>
                </div>
                <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">ХРАНИЛИЩЕ ФАЙЛОВ</div>
                  <div className="mt-2 text-[11px] font-black uppercase tracking-wide text-zinc-950">
                    {!(sys as any)?.s3?.configured
                      ? "НЕ НАСТРОЕНО"
                      : !(sys as any)?.s3?.probed
                        ? "НАСТРОЕНО, НЕ ПРОВЕРЕНО"
                        : (sys as any)?.s3?.ok
                          ? "BUCKET ДОСТУПЕН"
                          : "НЕТ ДОСТУПА"}
                  </div>
                  <div className="mt-2 break-all text-[10px] font-bold text-zinc-600">
                    {String((sys as any)?.s3?.bucket || "—")} · {String((sys as any)?.s3?.endpoint || "—")}
                  </div>
                  {(sys as any)?.s3?.reason ? (
                    <div className="mt-1 break-all text-[10px] font-bold text-rose-700">{String((sys as any)?.s3?.reason)}</div>
                  ) : null}
                  <div className="mt-3 flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      className="text-[10px] font-black uppercase tracking-widest text-zinc-700 underline disabled:opacity-50"
                      disabled={sysLoading || !(sys as any)?.s3?.configured}
                      onClick={() => void probeStatus()}
                    >
                      {sysLoading ? "Проверяем…" : (sys as any)?.s3?.probed ? "Проверить снова" : "Проверить доступ"}
                    </button>
                    <a href="/admin/settings#storage" className="text-[10px] font-black uppercase tracking-widest text-amber-700 underline">
                      Настроить хранилище →
                    </a>
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
                <p className="text-xs text-zinc-500">Удаление из базы отключено. Проверьте материалы в редакторе; ненужные модули можно переместить в архив без потери истории.</p>
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
