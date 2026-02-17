"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/app/shell";
import { InsightCard } from "@/components/app/insight-card";
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

type FeedItem = {
  kind: string;
  created_at: string;
  title: string;
};

export default function DashboardPage() {
  const { user } = useAuth();
  const [feedAll, setFeedAll] = useState<FeedItem[]>([]);
  const [assignments, setAssignments] = useState<AssignmentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [quoteNonce, setQuoteNonce] = useState(0);

  async function loadData() {
    try {
      setError(null);
      setLoading(true);
      const [af, as] = await Promise.all([
        apiFetch<{ items: FeedItem[] }>("/me/activity-feed"),
        apiFetch<{ items: AssignmentItem[] }>("/me/assignments"),
      ]);
      setFeedAll(af.items || []);
      setAssignments(as.items || []);
    } catch (e) {
      const anyErr = e as any;
      const msg = e instanceof Error ? e.message : "Не удалось загрузить данные";
      const rid = String(anyErr?.requestId || anyErr?.request_id || "").trim();
      setError((msg || "Не удалось загрузить данные") + (rid ? ` (код: ${rid})` : ""));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setQuoteNonce(Date.now());
    loadData();
  }, []);

  const didSomethingToday = useMemo(() => {
    const day = new Date().toISOString().slice(0, 10);
    return (feedAll || []).some((it) => String(it.created_at || "").slice(0, 10) === day);
  }, [feedAll]);

  return (
    <AppShell>
      <div className="h-[calc(100vh-80px)] overflow-hidden flex flex-col mx-auto max-w-7xl px-6 py-6 lg:py-10">
        {error ? (
          <div className="mb-6 rounded-2xl border border-rose-500/20 bg-rose-500/5 p-4 text-sm text-rose-400 font-bold uppercase tracking-widest text-center">
            {error}
          </div>
        ) : null}
        {/* Top Section: Profile & Quote */}
        <div className="grid lg:grid-cols-12 gap-6 items-end mb-8">
          <div className="lg:col-span-7">
            
            <h1 className="text-6xl font-black tracking-tighter text-zinc-950 leading-none uppercase">
              {user?.name ? user.name.split(' ')[0] : "TEAM"}
            </h1>
            <p className="mt-4 text-lg text-zinc-500 font-medium uppercase tracking-tight">
              Умный прогресс — <span className="text-[#284e13]">КАРКАС ТАЙГИ</span>.
            </p>
          </div>
          <div className="lg:col-span-5">
            {loading ? (
              <Skeleton className="h-[100px] rounded-[24px] bg-zinc-100" />
            ) : (
              <div className="relative group">
                <div className="absolute -inset-1 bg-gradient-to-r from-[#fe9900]/25 to-[#284e13]/15 rounded-[32px] blur opacity-25 group-hover:opacity-100 transition duration-1000" />
                <div className="relative border border-zinc-200 bg-white/70 backdrop-blur-xl rounded-[28px] overflow-hidden shadow-2xl shadow-zinc-950/10">
                  <InsightCard nonce={quoteNonce} />
                </div>
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
