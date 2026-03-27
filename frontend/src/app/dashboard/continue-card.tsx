"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";

export function ContinueCard() {
  const [inProgress, setInProgress] = useState<{
    id: string;
    title: string;
    progressText: string;
    pct: number;
  } | null>(null);

  const loadInFlightRef = useRef(false);
  const lastLoadAtRef = useRef(0);

  async function loadOverview(opts?: { force?: boolean }) {
    const now = Date.now();
    if (loadInFlightRef.current) return;
    if (!opts?.force && now - Number(lastLoadAtRef.current || 0) < 2500) return;
    loadInFlightRef.current = true;
    lastLoadAtRef.current = now;
    try {
      // Prefer the module where the user most recently COMPLETED a step (read confirmation or passed quiz).
      try {
        const hist = await apiFetch<{ items: Array<{ kind?: string; passed?: boolean | null; module_id?: string | null }> }>(
          "/me/history?limit=50"
        );
        const items0 = Array.isArray(hist?.items) ? hist.items : [];
        const lastCompleted = items0.find((it) => {
          const k = String(it?.kind || "").trim().toLowerCase();
          if (k === "lesson") return true;
          if (k === "quiz") return Boolean(it?.passed);
          return false;
        });
        const lastModuleId = String((lastCompleted as any)?.module_id || "").trim();
        if (lastModuleId) {
          const ov = await apiFetch<{
            items: Array<{
              id: string;
              title: string;
              progress?: {
                completed: boolean;
              };
            }>;
          }>("/modules/overview");

          const items = Array.isArray((ov as any)?.items) ? ((ov as any).items as any[]) : [];
          const idx = items.findIndex((m) => String(m?.id || "") === String(lastModuleId));

          const isCompleted = (m: any) => Boolean(m?.progress?.completed);

          let pick: any = null;
          if (idx >= 0) {
            if (!isCompleted(items[idx])) {
              pick = items[idx];
            } else {
              pick = items.slice(idx + 1).find((m) => m && !isCompleted(m)) || items.find((m) => m && !isCompleted(m));
            }
          } else {
            pick = items.find((m) => m && !isCompleted(m));
          }

          if (pick?.id) {
            const prog = await apiFetch<{ passed: number; total: number }>(`/progress/modules/${encodeURIComponent(String(pick.id))}`);
            const total = Math.max(1, Number((prog as any)?.total || 0));
            const passed = Math.max(0, Number((prog as any)?.passed || 0));
            const pct = Math.round((passed / total) * 100);
            setInProgress({ id: String(pick.id), title: String(pick.title || ""), progressText: `${passed}/${total}`, pct });
            return;
          }
        }
      } catch {
        // ignore: fallback below
      }

      const resp = await apiFetch<{
        items: Array<{
          id: string;
          title: string;
          progress?: {
            read_count: number;
            total_lessons: number;
            passed_count: number;
            final_passed: boolean;
            completed: boolean;
          };
        }>;
      }>("/modules/overview");

      const items = resp.items || [];
      const candidate = items.find((m) => {
        const p = m.progress;
        if (!p) return false;
        if (p.completed) return false;
        return (p.read_count || 0) > 0 || (p.passed_count || 0) > 0 || Boolean(p.final_passed);
      });

      if (candidate) {
        const prog = await apiFetch<{ passed: number; total: number }>(`/progress/modules/${encodeURIComponent(candidate.id)}`);
        const total = Math.max(1, Number((prog as any)?.total || 0));
        const passed = Math.max(0, Number((prog as any)?.passed || 0));
        const pct = Math.round((passed / total) * 100);
        setInProgress({ id: candidate.id, title: candidate.title, progressText: `${passed}/${total}`, pct });
      } else {
        setInProgress(null);
      }
    } catch {
    } finally {
      loadInFlightRef.current = false;
    }
  }

  useEffect(() => {
    void loadOverview();
  }, []);

  useEffect(() => {
    const onRefresh = (e: any) => {
      try {
        const reason = String(e?.detail?.reason || "").trim().toLowerCase();
        if (reason === "keepalive") return;
        if (reason === "progress") {
          void loadOverview({ force: true });
          return;
        }
      } catch {
      }
      void loadOverview();
    };
    window.addEventListener("corelms:refresh-me", onRefresh as EventListener);
    return () => window.removeEventListener("corelms:refresh-me", onRefresh as EventListener);
  }, []);

  return (
    <div className="relative group h-full">
      <div className="absolute -inset-0.5 bg-gradient-to-r from-[#fe9900]/25 to-[#284e13]/15 rounded-[32px] blur opacity-0 group-hover:opacity-100 transition duration-700" />
      <div className="relative h-full overflow-hidden rounded-[28px] border border-zinc-200 bg-white/70 p-8 flex flex-col justify-between transition-all duration-300 hover:bg-white shadow-2xl shadow-zinc-950/10">
        <div>
          <div className="text-[10px] font-black text-[#fe9900] uppercase tracking-[0.3em] mb-4">Начни прямо сейчас</div>
          <h3 className="text-3xl font-black text-zinc-950 tracking-tighter uppercase leading-none mb-2">
            {inProgress?.title || "МОДУЛЬ СТАРТ"}
          </h3>
          <p className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">
            {inProgress ? "ПРОДОЛЖАЙТЕ ОБУЧЕНИЕ" : "ПОРА НАЧИНАТЬ ПЕРВЫЙ ЭТАП"}
          </p>
        </div>

        <div className="mt-8 flex items-end justify-between">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <span className="text-2xl font-black text-zinc-950 tabular-nums">{inProgress?.progressText || "0/15"}</span>
              <span className="text-[10px] font-black text-[#284e13] uppercase tracking-widest">ПРОЙДЕНО</span>
            </div>
            <div className="h-1 w-32 rounded-full bg-zinc-200 overflow-hidden">
              <div 
                className="h-full bg-[#fe9900] transition-all duration-1000" 
                style={{ width: `${inProgress?.pct || 0}%` }} 
              />
            </div>
          </div>

          <Link href={inProgress ? `/modules/${inProgress.id}` : "/modules"}>
            <Button className="h-14 px-10 rounded-2xl transition-all hover:scale-105 active:scale-95 shadow-xl shadow-[#fe9900]/15">
              {inProgress ? "ПРОДОЛЖИТЬ" : "НАЧАТЬ"}
            </Button>
          </Link>
        </div>
      </div>
    </div>
  );
}
