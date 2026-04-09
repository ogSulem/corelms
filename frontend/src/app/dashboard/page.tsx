"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/app/shell";
import { InsightCard } from "@/components/app/insight-card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ContinueCard } from "@/app/dashboard/continue-card";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/hooks/use-auth";

type AssignmentItem = {
  id: string;
  type: string;
  target_id: string;
  status: string;
  priority: number;
  deadline: string | null;
};

type MyProfile = {
  last_activity_at?: string | null;
};

type ProgressSummary = {
  modules_total: number;
  modules_completed: number;
  steps_total: number;
  steps_completed: number;
  percent: number;
};

export default function DashboardPage() {
  const { user } = useAuth();
  const [profile, setProfile] = useState<MyProfile | null>(null);
  const [assignments, setAssignments] = useState<AssignmentItem[]>([]);
  const [progress, setProgress] = useState<ProgressSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [quoteNonce, setQuoteNonce] = useState(0);

  const telegramSuppliersBaseUrl = String(process.env.NEXT_PUBLIC_TELEGRAM_SUPPLIERS_BASE_URL || "").trim();

  const loadInFlightRef = useRef(false);
  const lastLoadAtRef = useRef(0);

  async function loadData() {
    const now = Date.now();
    if (loadInFlightRef.current) return;
    if (now - Number(lastLoadAtRef.current || 0) < 2500) return;
    loadInFlightRef.current = true;
    lastLoadAtRef.current = now;
    try {
      setError(null);
      setLoading(true);
      const [p, as, pr] = await Promise.all([
        apiFetch<MyProfile>("/me/profile"),
        apiFetch<{ items: AssignmentItem[] }>("/me/assignments"),
        apiFetch<ProgressSummary>("/me/progress-summary"),
      ]);
      setProfile(p || null);
      setAssignments(as.items || []);
      setProgress(pr || null);
    } catch (e) {
      const anyErr = e as any;
      const msg = e instanceof Error ? e.message : "Не удалось загрузить данные";
      const rid = String(anyErr?.requestId || anyErr?.request_id || "").trim();
      setError((msg || "Не удалось загрузить данные") + (rid ? ` (код: ${rid})` : ""));
    } finally {
      setLoading(false);
      loadInFlightRef.current = false;
    }
  }

  useEffect(() => {
    setQuoteNonce(Date.now());
    loadData();
  }, []);

  useEffect(() => {
    const onRefresh = (e: any) => {
      try {
        const reason = String(e?.detail?.reason || "").trim().toLowerCase();
        if (reason === "keepalive") return;
      } catch {
      }
      void loadData();
    };

    let lastHiddenAt = 0;
    const onFocus = () => void loadData();
    const onVisibility = () => {
      const st = document.visibilityState;
      if (st === "hidden") {
        lastHiddenAt = Date.now();
        return;
      }
      if (st === "visible") {
        const hiddenForMs = lastHiddenAt ? Date.now() - lastHiddenAt : 0;
        if (hiddenForMs >= 30_000) void loadData();
      }
    };

    window.addEventListener("corelms:refresh-me", onRefresh as EventListener);
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("corelms:refresh-me", onRefresh as EventListener);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  const didSomethingToday = useMemo(() => {
    const day = new Date().toISOString().slice(0, 10);
    const last = String(profile?.last_activity_at || "");
    return last ? last.slice(0, 10) === day : false;
  }, [profile?.last_activity_at]);

  return (
    <AppShell>
      <div className="flex flex-col mx-auto max-w-7xl px-6 py-6 lg:py-10">
        {error ? (
          <div className="mb-6 rounded-2xl border border-rose-500/20 bg-rose-500/5 p-4 text-sm text-rose-400 font-bold uppercase tracking-widest text-center">
            {error}
          </div>
        ) : null}
        {/* Top Section: Profile & Quote */}
        <div className="grid lg:grid-cols-12 gap-6 items-end mb-8">
          <div className="lg:col-span-7">
            <div className="mb-4">
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-2xl border-[#fe9900]/35 bg-[#fe9900]/10 hover:bg-[#fe9900]/15 hover:border-[#fe9900]/45 text-zinc-950 gap-2"
                  onClick={() => window.dispatchEvent(new CustomEvent("corelms:open-quickstart"))}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <path
                      d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10Z"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M9.3 9.4a2.8 2.8 0 1 1 4.3 2.4c-.9.6-1.6 1.3-1.6 2.2v.3"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    <path d="M12 17.8h.01" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                  </svg>
                  <span>Быстрый старт</span>
                </Button>
              </div>
            </div>
            <h1 className="text-6xl font-black tracking-tighter text-zinc-950 leading-none uppercase">
              {user?.name ? user.name.split(' ')[0] : "TEAM"}
            </h1>
            {loading ? (
              <div className="mt-5">
                <Skeleton className="h-[72px] rounded-[24px] bg-zinc-100" />
              </div>
            ) : (
              <div className="mt-5">
                <div className="relative overflow-hidden rounded-[26px] border border-zinc-200 bg-white/70 backdrop-blur-xl p-5 shadow-2xl shadow-zinc-950/10">
                  <div className="absolute inset-0 pointer-events-none">
                    <div className="absolute -top-12 -left-12 h-40 w-40 rounded-full bg-[#fe9900]/18 blur-[70px]" />
                    <div className="absolute -bottom-12 -right-12 h-44 w-44 rounded-full bg-[#284e13]/14 blur-[70px]" />
                  </div>

                  <div className="relative">
                    <div className="flex items-end justify-between gap-4">
                      <div>
                        <div className="text-[10px] font-black uppercase tracking-[0.32em] text-zinc-500">Общий прогресс</div>
                        <div className="mt-2 text-sm font-black uppercase tracking-tight text-zinc-950">
                          {progress ? `${Number(progress.steps_completed || 0)} / ${Number(progress.steps_total || 0)} шагов` : "—"}
                        </div>
                        <div className="mt-1 text-[11px] font-bold text-zinc-600">
                          {progress ? `${Number(progress.modules_completed || 0)} / ${Number(progress.modules_total || 0)} модулей` : ""}
                        </div>
                      </div>

                      <div className="shrink-0 text-right">
                        <div className="text-[10px] font-black uppercase tracking-[0.32em] text-zinc-500">%</div>
                        <div className="mt-1 text-3xl font-black tracking-tighter text-zinc-950">
                          {progress ? `${Math.max(0, Math.min(100, Number(progress.percent || 0)))}%` : "0%"}
                        </div>
                      </div>
                    </div>

                    <div className="mt-4">
                      <div className="h-3 rounded-full bg-zinc-100 overflow-hidden border border-zinc-200">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-[#fe9900] to-[#284e13] transition-all duration-700"
                          style={{ width: `${progress ? Math.max(0, Math.min(100, Number(progress.percent || 0))) : 0}%` }}
                        />
                      </div>
                      <div className="mt-2 flex items-center justify-between text-[10px] font-black uppercase tracking-widest text-zinc-500">
                        <span>Старт</span>
                        <span>Финиш</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
          <div className="lg:col-span-5">
            {loading ? (
              <Skeleton className="h-[100px] rounded-[24px] bg-zinc-100" />
            ) : (
              <div className="relative">
                <div className="pointer-events-none absolute -inset-1 bg-gradient-to-r from-[#fe9900]/25 to-[#284e13]/15 rounded-[32px] blur opacity-25" />
                <div className="relative border border-zinc-200 bg-white/70 backdrop-blur-xl rounded-[28px] overflow-hidden shadow-2xl shadow-zinc-950/10">
                  <InsightCard nonce={quoteNonce} />
                </div>
                {telegramSuppliersBaseUrl ? (
                  <div className="mt-4">
                    <Button asChild className="w-full rounded-2xl bg-[#229ED9] hover:bg-[#1b8bbf] text-white gap-2">
                      <a href={telegramSuppliersBaseUrl} target="_blank" rel="noreferrer">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                          <path
                            d="M21.8 4.7c.3-1.3-1-2.3-2.2-1.9L3.7 9.2c-1.4.5-1.4 2.4 0 2.9l3.9 1.3 1.5 4.7c.4 1.2 1.9 1.6 2.8.7l2.2-2.1 4.3 3.2c1 .8 2.4.2 2.7-1.1l3.7-14.1Z"
                            fill="currentColor"
                            opacity="0.95"
                          />
                          <path
                            d="M9.1 13.1 18.5 6.9c.2-.1.4.2.2.4l-7.8 7.6c-.3.3-.5.7-.6 1.1l-.3 2.4c0 .3-.5.4-.6.1l-1.2-4.1c-.2-.7.1-1.4.8-1.8Z"
                            fill="currentColor"
                          />
                        </svg>
                        <span>База поставщиков</span>
                      </a>
                    </Button>
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </div>

        {/* Main Grid: Continue & Boost */}
        <div className="grid lg:grid-cols-2 gap-6 flex-1 min-h-0">
          {/* Left: Continue Learning */}
          <div className="h-full">
            {loading ? (
              <Skeleton className="h-full rounded-[32px] bg-zinc-100" />
            ) : (
              <ContinueCard />
            )}
          </div>

          {/* Right: Career Boost / Daily Goal */}
          <div className="h-full">
            <div className="relative h-full overflow-hidden rounded-[28px] border border-zinc-200 bg-white/70 p-10 flex flex-col justify-between group shadow-2xl shadow-zinc-950/10">
              <div className="absolute -bottom-8 -right-8 text-[120px] font-black italic text-zinc-950/[0.03] pointer-events-none group-hover:text-[#fe9900]/[0.07] transition-all duration-700 select-none">
                ЦЕЛЬ
              </div>
              
              <div>
                <div className="text-[10px] font-black text-[#fe9900] uppercase tracking-[0.4em] mb-4">Ежедневный импульс</div>
                <h3 className="text-4xl font-black text-zinc-950 tracking-tighter uppercase leading-tight max-w-xs">
                  Твоя цель на сегодня
                </h3>
              </div>

              <div className="flex items-center justify-between mt-auto">
                <div className="max-w-[200px]">
                  <p className="text-xs font-bold text-zinc-500 uppercase leading-relaxed tracking-wider">
                    {didSomethingToday 
                      ? "Цель достигнута. Твои навыки растут прямо сейчас." 
                      : "Выполни любое действие, чтобы зафиксировать прогресс дня."}
                  </p>
                </div>
                
                <div className="relative">
                  <div
                    className={`h-28 w-28 rounded-full border-4 flex flex-col items-center justify-center transition-all duration-700 ${
                      didSomethingToday
                        ? "border-[#284e13] bg-[#284e13]/10 text-[#284e13] shadow-[0_0_50px_rgba(40,78,19,0.18)]"
                        : "border-zinc-200 bg-zinc-50 text-zinc-300"
                    }`}
                  >
                    <span className="text-4xl font-black">{didSomethingToday ? "✓" : "0"}</span>
                    <span className="text-[10px] font-black uppercase tracking-widest mt-1">/ 1</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Bottom Task Bar (Minimal) */}
        <div className="mt-8 flex items-center justify-between border-t border-zinc-200 pt-6">
          <div className="flex items-center gap-6">
            {assignments.filter(a => a.status !== 'completed').length > 0 && (
              <Link href="/modules" className="flex items-center gap-2 group">
                <span className="text-[10px] font-black text-zinc-600 uppercase tracking-widest group-hover:text-[#284e13] transition-colors">
                  Задач в работе: {assignments.filter(a => a.status !== 'completed').length}
                </span>
                <span className="text-[#fe9900] text-xs">→</span>
              </Link>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
