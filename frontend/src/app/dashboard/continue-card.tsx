"use client";

import { useEffect, useState } from "react";
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

  useEffect(() => {
    (async () => {
      try {
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
          const p = candidate.progress!;
          const total = Math.max(1, p.total_lessons || 0);
          const pct = Math.round((p.passed_count / total) * 100);
          setInProgress({
            id: candidate.id,
            title: candidate.title,
            progressText: `${p.passed_count}/${total}`,
            pct,
          });
        } else {
          setInProgress(null);
        }
      } catch { /* ignore */ }
    })();
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
              <span className="text-[10px] font-black text-[#284e13] uppercase tracking-widest">ГОТОВО</span>
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
