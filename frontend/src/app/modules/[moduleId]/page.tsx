"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ChevronLeft } from "lucide-react";

import { AppShell } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LockIcon } from "@/components/ui/lock";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";

type ModuleMeta = {
  id: string;
  title: string;
  description: string | null;
  difficulty: number;
  category: string | null;
  is_active: boolean;
};

type ModuleAsset = {
  asset_id: string;
  object_key: string;
  original_filename: string;
  mime_type: string | null;
};

type Submodule = {
  id: string;
  module_id: string;
  title: string;
  order: number;
  quiz_id: string;
};

type ProgressData = {
  module_id: string;
  total: number;
  passed: number;
  final_submodule_id: string | null;
  final_quiz_id: string | null;
  final_passed: boolean;
  final_best_score: number | null;
  completed: boolean;
  submodules: {
    submodule_id: string;
    quiz_id: string;
    read: boolean;
    passed: boolean;
    best_score: number | null;
    last_score?: number | null;
    last_passed?: boolean | null;
    locked?: boolean;
    locked_reason?: string | null;
    is_final?: boolean;
  }[];
};

export default function ModulePage() {
  const params = useParams<{ moduleId: string }>();
  const search = useSearchParams();
  const moduleId = params.moduleId;

  const [moduleMeta, setModuleMeta] = useState<ModuleMeta | null>(null);
  const [submodules, setSubmodules] = useState<Submodule[]>([]);
  const [progress, setProgress] = useState<ProgressData | null>(null);
  const [moduleAssets, setModuleAssets] = useState<ModuleAsset[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  function decodeLegacyPercentUnicode(input: string): string {
    const raw = String(input || "").trim();
    if (!raw) return "";
    try {
      const replaced = raw.replace(/%[uU]([0-9a-fA-F]{4})/g, (_, hex) => {
        try {
          return String.fromCharCode(Number.parseInt(hex, 16));
        } catch {
          return _;
        }
      });
      const decoded = decodeURIComponent(replaced);
      return decoded.normalize("NFC");
    } catch {
      try {
        return raw.normalize("NFC");
      } catch {
        return raw;
      }
    }
  }

  function formatAssetTitle(name: string): string {
    const raw = decodeLegacyPercentUnicode(String(name || "").trim());
    return raw
      .replace(/^\s*\d{1,3}\s*[\.)]\s*/u, "")
      .replace(/^\s*\d{1,3}\s*[-_:]\s*/u, "")
      .trim();
  }

  const fetchModuleData = async () => {
    if (!moduleId) return;
    try {
      setError(null);
      setLoading(true);

      const [meta, s, p, ma] = await Promise.all([
        apiFetch<ModuleMeta>(`/modules/${moduleId}`),
        apiFetch<Submodule[]>(`/modules/${moduleId}/submodules`),
        apiFetch<ProgressData>(`/progress/modules/${moduleId}`),
        apiFetch<{ assets: ModuleAsset[] }>(`/modules/${moduleId}/assets`),
      ]);

      setModuleMeta(meta);
      setSubmodules(s);
      setProgress(p);
      setModuleAssets(ma.assets || []);
    } catch (e) {
      const anyErr = e as any;
      const msg = e instanceof Error ? e.message : "Не удалось загрузить модуль. Проверьте подключение.";
      const rid = String(anyErr?.requestId || anyErr?.request_id || "").trim();
      setError((msg || "Не удалось загрузить модуль. Проверьте подключение.") + (rid ? ` (код: ${rid})` : ""));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchModuleData();
  }, [moduleId]);

  useEffect(() => {
    if (!moduleId) return;
    let inFlight = false;
    const safeReload = () => {
      if (inFlight) return;
      inFlight = true;
      Promise.resolve(fetchModuleData()).finally(() => {
        inFlight = false;
      });
    };

    const onRefresh = () => safeReload();
    const onFocus = () => safeReload();
    const onVisibility = () => {
      if (document.visibilityState === "visible") safeReload();
    };

    window.addEventListener("corelms:refresh-me", onRefresh as EventListener);
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("corelms:refresh-me", onRefresh as EventListener);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [moduleId]);

  async function onOpenAsset(assetId: string) {
    try {
      const data = await apiFetch<{ asset_id: string; download_url: string }>(
        `/assets/${assetId}/presign-download?action=download`
      );
      window.open(data.download_url, "_blank", "noopener,noreferrer");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("corelms:toast", {
            detail: {
              title: "НЕ УДАЛОСЬ ОТКРЫТЬ ФАЙЛ",
              description: msg || "Проверьте доступ к хранилищу и попробуйте снова",
            },
          })
        );
      }
    }
  }

  const progressMap = useMemo(() => {
    const m = new Map<string, any>();
    progress?.submodules.forEach((s) => m.set(s.submodule_id, s));
    return m;
  }, [progress]);

  function hasAttempt(p: any): boolean {
    if (!p) return false;
    const scorePresent = p.last_score !== undefined && p.last_score !== null;
    const passedPresent = p.last_passed !== undefined && p.last_passed !== null;
    return Boolean(scorePresent || passedPresent);
  }

  function displayScore(p: any): number | null {
    if (!hasAttempt(p)) return null;
    return typeof p?.last_score === "number" ? p.last_score : 0;
  }

  const currentSubmoduleId = useMemo(() => {
    if (!submodules.length || !progressMap.size) return null;
    for (const s of submodules) {
      const st = progressMap.get(s.id);
      if (st?.locked) continue;
      if (!st?.passed) return s.id;
    }
    return null;
  }, [submodules, progressMap]);

  const quizTotals = useMemo(() => {
    if (!progress) return { passed: 0, total: 0 };
    return { passed: progress.passed, total: progress.total };
  }, [progress]);

  const finalExamLocked = useMemo(() => {
    if (!progress) return true;
    return progress.submodules.some(s => !s.passed);
  }, [progress]);

  const continueHref = useMemo(() => {
    if (currentSubmoduleId) {
      return `/submodules/${encodeURIComponent(currentSubmoduleId)}?module=${encodeURIComponent(moduleId)}`;
    }
    if (progress?.final_quiz_id && !finalExamLocked && !progress.final_passed) {
      return `/quizzes/${encodeURIComponent(String(progress.final_quiz_id))}?module=${encodeURIComponent(moduleId)}`;
    }
    return "";
  }, [currentSubmoduleId, finalExamLocked, moduleId, progress?.final_passed, progress?.final_quiz_id]);

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-6 py-10">
            <div className="flex items-start justify-between gap-6">
              <div className="flex-1">
                <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900] mb-2">Программа обучения</div>
                <h1 className="text-4xl font-black tracking-tighter text-zinc-950 uppercase leading-none">
                  {moduleMeta?.title || (loading ? "Загрузка…" : "Модуль")}
                </h1>
                <div className="mt-6 max-w-md">
                  <div className="flex items-center justify-between text-[10px] font-black uppercase tracking-widest text-zinc-600 mb-2">
                    <div>Прогресс модуля</div>
                    <div className="tabular-nums text-[#284e13]">
                      {quizTotals.passed} / {quizTotals.total}
                    </div>
                  </div>
                  <div className="h-1 w-full rounded-full bg-zinc-200 overflow-hidden">
                    <div 
                      className="h-full bg-[#fe9900] transition-all duration-1000"
                      style={{ width: `${quizTotals.total > 0 ? Math.round((quizTotals.passed / quizTotals.total) * 100) : 0}%` }}
                    />
                  </div>
                </div>

                <div className="mt-6 flex flex-wrap items-center gap-3">
                  {continueHref ? (
                    <Link href={continueHref}>
                      <Button className="h-12 rounded-2xl px-8 font-black uppercase tracking-widest text-[10px]">
                        Продолжить обучение
                      </Button>
                    </Link>
                  ) : (
                    <Button disabled className="h-12 rounded-2xl px-8 font-black uppercase tracking-widest text-[10px]">
                      Продолжить обучение
                    </Button>
                  )}
                  {!continueHref && progress?.final_quiz_id && finalExamLocked ? (
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">
                      Сначала завершите все уроки
                    </div>
                  ) : null}
                </div>
              </div>
              <Link href="/modules">
                <Button
                  variant="ghost"
                  size="sm"
                  className="rounded-xl"
                >
                  <ChevronLeft className="mr-2 h-4 w-4" />
                  назад
                </Button>
              </Link>
            </div>

        {error ? (
          <div className="mt-8 rounded-3xl border border-red-500/30 bg-red-500/10 p-12 text-center shadow-2xl">
            <div className="text-red-200 text-lg font-medium mb-6">{error}</div>
            <Button onClick={() => fetchModuleData()} variant="outline" className="border-red-500/30 hover:bg-red-500/15 h-12 px-8 rounded-xl">
              Попробовать снова
            </Button>
          </div>
        ) : (
          <div className="mt-8 grid gap-8 lg:grid-cols-3">
            <Card className="lg:col-span-1 relative overflow-hidden border border-zinc-200 bg-white/70 backdrop-blur-md rounded-[28px] shadow-2xl shadow-zinc-950/10">
              <div className="absolute left-0 top-0 h-full w-[2px] bg-gradient-to-b from-[#fe9900]/60 to-transparent" />
              <CardHeader className="p-8">
                <CardTitle className="text-xs font-black uppercase tracking-[0.3em] text-zinc-500">Материалы</CardTitle>
              </CardHeader>
              <CardContent className="px-8 pb-8 pt-0">
                {loading ? (
                  <div className="space-y-4">
                    <Skeleton className="h-16 w-full rounded-2xl bg-zinc-100" />
                    <Skeleton className="h-16 w-full rounded-2xl bg-zinc-100" />
                  </div>
                ) : moduleAssets.length === 0 ? (
                  <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600 py-12 text-center border border-dashed border-zinc-200 rounded-2xl">
                    Нет файлов
                  </div>
                ) : (
                  <div className="grid gap-3">
                    {moduleAssets.map((a, idx) => (
                      <div key={a.asset_id} className="group relative overflow-hidden rounded-2xl border border-zinc-200 bg-white/70 p-4 transition-all duration-300 hover:bg-white">
                        <div className="flex items-center justify-between gap-4">
                          <div className="min-w-0">
                            <div className="flex items-center gap-3 min-w-0">
                              <span className="shrink-0 text-[10px] font-black uppercase tracking-widest text-zinc-500 tabular-nums">
                                {String(idx + 1).padStart(2, "0")}
                              </span>
                              <div className="min-w-0 truncate text-sm font-bold text-zinc-950 transition-colors">
                                {formatAssetTitle(a.original_filename)}
                              </div>
                            </div>
                          </div>
                          <button
                            onClick={() => onOpenAsset(a.asset_id)}
                            className="shrink-0 rounded-xl bg-[#fe9900]/10 border border-[#fe9900]/25 px-3 py-2 text-[9px] font-black text-[#284e13] uppercase tracking-widest hover:bg-[#fe9900] hover:text-zinc-950 transition-all active:scale-95"
                          >
                            открыть
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <div className="lg:col-span-2 space-y-6">
              <div className="rounded-[28px] border border-zinc-200 bg-white/70 backdrop-blur-md p-8 shadow-2xl shadow-zinc-950/10">
                <div className="mb-8 flex items-center justify-between">
                  <h2 className="text-xs font-black uppercase tracking-[0.3em] text-zinc-500">Путь обучения</h2>
                </div>
                {loading ? (
                  <div className="space-y-4">
                    <Skeleton className="h-24 w-full rounded-[24px] bg-zinc-100" />
                    <Skeleton className="h-24 w-full rounded-[24px] bg-zinc-100" />
                  </div>
                ) : submodules.length === 0 ? (
                  <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600 py-20 text-center border border-dashed border-zinc-200 rounded-[24px]">
                    Нет уроков
                  </div>
                ) : (
                  <div className="relative">
                    <div className="absolute left-[15px] top-2 bottom-2 w-px bg-zinc-200" />
                    <div className="grid gap-4">
                      {submodules.map((s) => {
                        const p = progressMap.get(s.id);
                        const passed = !!p?.passed;
                        const read = !!p?.read;
                        const locked = !!p?.locked;
                        const lockedReason = String(p?.locked_reason || "").trim();
                        const isCurrent = currentSubmoduleId === s.id;
                        const score = displayScore(p);

                        const dotClass = locked
                          ? "bg-zinc-300"
                          : passed
                          ? "bg-[#284e13]"
                          : isCurrent
                          ? "bg-[#fe9900]"
                          : "bg-zinc-400";

                        const itemClass = `relative rounded-[24px] border px-6 py-5 transition-all duration-300 ${
                          locked
                            ? "border-zinc-200 bg-zinc-50 opacity-50 cursor-not-allowed"
                            : isCurrent
                            ? "border-[#fe9900]/40 bg-[#fe9900]/10 scale-[1.01]"
                            : "border-zinc-200 bg-white/70 hover:bg-white"
                        }`;

                        const rowContent = (
                          <div className="flex items-start justify-between gap-6">
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-3">
                                <span className="text-sm font-black text-zinc-600 tabular-nums uppercase">{String(s.order).padStart(2, '0')}</span>
                                <h4 className="text-base font-black text-zinc-950 uppercase tracking-tighter break-words leading-snug">
                                  {s.title}
                                </h4>
                              </div>
                              {locked && lockedReason ? (
                                <div className="mt-2 text-[9px] font-black uppercase tracking-widest text-zinc-500">
                                  {lockedReason}
                                </div>
                              ) : null}
                              <div className="mt-4 flex flex-wrap items-center gap-3">
                                <div className="flex items-center gap-2">
                                  <div
                                    className={`rounded-lg px-3 py-1 text-[9px] font-black uppercase tracking-widest border transition-all duration-500 ${
                                      read
                                        ? "bg-[#284e13]/10 border-[#284e13]/20 text-[#284e13]"
                                        : "bg-zinc-100 border-zinc-200 text-zinc-600"
                                    }`}
                                  >
                                    ТЕОРИЯ
                                  </div>
                                  <div
                                    className={`flex items-center gap-2 rounded-lg px-3 py-1 text-[9px] font-black uppercase tracking-widest border transition-all duration-500 ${
                                      passed
                                        ? "bg-[#284e13]/10 border-[#284e13]/20 text-[#284e13]"
                                        : hasAttempt(p)
                                        ? "bg-rose-50 border-rose-200 text-rose-700"
                                        : "bg-zinc-100 border-zinc-200 text-zinc-600"
                                    }`}
                                  >
                                    <span>ТЕСТ</span>
                                    <span
                                      className={`tabular-nums ${
                                        passed
                                          ? "text-[#284e13]"
                                          : score !== null
                                          ? "text-rose-700"
                                          : "text-zinc-600"
                                      }`}
                                    >
                                      {typeof score === "number" ? `${score}%` : "—"}
                                    </span>
                                  </div>
                                </div>
                              </div>
                            </div>
                            <div className="shrink-0 pt-1">
                              {locked ? (
                                <LockIcon className="w-4 h-4 text-zinc-400" />
                              ) : passed ? (
                                <div className="flex items-center justify-center w-8 h-8 rounded-full bg-[#284e13]/10 border border-[#284e13]/20 text-[#284e13] text-sm font-black">✓</div>
                              ) : isCurrent ? (
                                <div className="h-8 w-8 rounded-full bg-[#fe9900]/10 border border-[#fe9900]/25 flex items-center justify-center">
                                  <div className="h-1.5 w-1.5 rounded-full bg-[#fe9900] animate-ping" />
                                </div>
                              ) : null}
                            </div>
                          </div>
                        );

                        const dot = (
                          <div className="relative z-10 flex justify-center w-8">
                            <div className={`mt-6 h-2.5 w-2.5 rounded-full border border-white transition-all duration-700 ${dotClass}`} />
                          </div>
                        );

                        if (locked) {
                          return (
                            <div key={s.id} className="flex gap-2 opacity-50 grayscale">
                              {dot}
                              <div className={`${itemClass} flex-1`}>{rowContent}</div>
                            </div>
                          );
                        }

                        return (
                          <Link key={s.id} href={`/submodules/${s.id}?module=${encodeURIComponent(moduleId)}`} className="flex gap-2 group outline-none">
                            {dot}
                            <div className={`${itemClass} flex-1 group-hover:scale-[1.01] active:scale-[0.99]`}>{rowContent}</div>
                          </Link>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
                
                {progress?.final_quiz_id && !loading && (
                  <div className="mt-14 space-y-5">
                    <div className="flex items-center gap-5 px-2">
                      <div className="h-px flex-1 bg-zinc-200" />
                      <div className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.3em]">Финальная аттестация</div>
                      <div className="h-px flex-1 bg-zinc-200" />
                    </div>
                    
                    <div className={`relative rounded-3xl border p-8 transition-all duration-700 ${
                      finalExamLocked 
                      ? "border-zinc-200 bg-white/70 opacity-50 grayscale" 
                      : progress.final_passed
                      ? "border-[#284e13]/25 bg-[#284e13]/5 shadow-[0_0_50px_rgba(40,78,19,0.06)]"
                      : "border-[#fe9900]/25 bg-[#fe9900]/5 shadow-[0_0_50px_rgba(254,153,0,0.06)]"
                    }`}>
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-10">
                        <div className="flex-1">
                          <h3 className="text-2xl font-black text-zinc-950 flex items-center gap-4 uppercase tracking-tighter">
                            {!finalExamLocked && !progress.final_passed && <div className="w-2.5 h-2.5 rounded-full bg-amber-400 animate-ping" />}
                            Итоговый экзамен модуля
                          </h3>
                          <p className="mt-3 text-sm text-zinc-600 max-w-lg leading-relaxed font-medium">
                            {finalExamLocked 
                              ? "Доступ откроется автоматически после успешного завершения всех уроков и промежуточных тестов модуля." 
                              : "Комплексная проверка знаний по всем темам. Результат фиксируется в отчётах и аналитике."}
                          </p>
                        </div>
                        
                        <div className="shrink-0">
                          {finalExamLocked ? (
                            <div className="p-5 bg-white rounded-2xl border border-zinc-200 inline-flex shadow-sm">
                              <LockIcon className="w-8 h-8 text-zinc-700" />
                            </div>
                          ) : (
                            <Link href={`/quizzes/${progress.final_quiz_id}?module=${moduleId}`}>
                              <Button size="lg" className={`px-12 h-16 rounded-2xl font-black text-lg shadow-2xl transition-all hover:scale-[1.03] active:scale-[0.97] uppercase tracking-widest ${progress.final_passed ? "bg-[#284e13] hover:bg-[#21410f] text-white" : "bg-[#fe9900] hover:bg-[#f48f00] text-zinc-950"}`}>
                                {progress.final_passed ? "Пересдать" : "Начать"}
                              </Button>
                            </Link>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
