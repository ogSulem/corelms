"use client";

import { useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/app/shell";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/hooks/use-auth";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type MyProfile = {
  id: string;
  name: string;
  role: string;
  position: string | null;
  xp: number;
  level: number;
  streak: number;
};

type FeedItem = {
  kind: string;
  created_at: string;
  title: string;
  subtitle?: string | null;
  status?: string | null;
  score?: number | null;
  passed?: boolean | null;
  count?: number | null;
  duration_seconds?: number | null;
  module_id?: string | null;
  module_title?: string | null;
  submodule_id?: string | null;
  submodule_title?: string | null;
  href?: string | null;
};

type HistoryItem = {
  id: string;
  created_at: string;
  kind: string;
  title: string;
  subtitle?: string | null;
  status?: string | null;
  score?: number | null;
  passed?: boolean | null;
  duration_seconds?: number | null;
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

type FeedFilter = "all" | "quiz_attempt" | "lesson" | "asset";

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m <= 0) return `${s}S`;
  return `${m}M ${s}S`;
}

export default function AccountPage() {
  const [profile, setProfile] = useState<MyProfile | null>(null);
  const [feed, setFeed] = useState<HistoryItem[]>([]);
  const [feedFilter, setFeedFilter] = useState<FeedFilter>("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        setError(null);
        setLoading(true);

        const p = await apiFetch<MyProfile>("/me/profile");
        setProfile(p);

        const hist = await apiFetch<{ items: HistoryItem[] }>(`/me/history?limit=200`);
        const items = Array.isArray(hist?.items) ? hist.items : [];
        const filtered = feedFilter === "all" ? items : items.filter((it) => it.kind === feedFilter);
        setFeed(filtered);
      } catch (e) {
        setError("НЕ УДАЛОСЬ ЗАГРУЗИТЬ ДАННЫЕ ПРОФИЛЯ");
      } finally {
        setLoading(false);
      }
    })();
  }, [feedFilter]);

  const level = profile?.level ?? 1;
  const xp = profile?.xp ?? 0;
  const streak = profile?.streak ?? 0;
  const nextLevelXp = level * 100;
  const prevLevelXp = (level - 1) * 100;
  const inLevel = Math.max(0, xp - prevLevelXp);
  const levelSpan = Math.max(1, nextLevelXp - prevLevelXp);
  const levelProgress = Math.max(0, Math.min(100, Math.round((inLevel / levelSpan) * 100)));

  const achievements = useMemo(() => {
    const hasQuizAttempt = (feed || []).some((it) => it.kind === "quiz_attempt");
    const hasLesson = (feed || []).some((it) => it.kind === "lesson");
    const hasAsset = (feed || []).some((it) => it.kind === "asset");

    return [
      { key: "first_step", title: "ПЕРВЫЙ ШАГ", desc: "АКТИВНОСТЬ ЗАФИКСИРОВАНА", done: (feed || []).length > 0 },
      { key: "first_quiz", title: "ПЕРВЫЙ ТЕСТ", desc: "ПОПЫТКА ЗАСЧИТАНА", done: hasQuizAttempt },
      { key: "streak_3", title: "СТРИК 3", desc: "РИТМ СОЗДАН", done: streak >= 3 },
      { key: "streak_7", title: "СТРИК 7", desc: "ПРИВЫЧКА СФОРМИРОВАНА", done: streak >= 7 },
      { key: "xp_100", title: "100 XP", desc: "ПРОГРЕСС РАСТЁТ", done: xp >= 100 },
      { key: "lvl_5", title: "УРОВЕНЬ 5", desc: "ВЫШЕ КВАЛИФИКАЦИЯ", done: level >= 5 },
    ];
  }, [feed, level, streak, xp]);

  const heroStats = useMemo(() => {
    return [
      { key: "xp", label: "XP", value: String(xp), hint: "Общий опыт" },
      { key: "level", label: "Уровень", value: String(level), hint: "Текущий ранг" },
      { key: "streak", label: "Серия", value: `${streak} дн.`, hint: "Ритм обучения" },
    ];
  }, [level, streak, xp]);

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-6 py-12 lg:py-20">
        <div className="mb-16">
          <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900] mb-2">Профиль</div>
          <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-8">
            <h1 className="text-5xl font-black tracking-tighter text-zinc-950 uppercase leading-none">
              {profile?.name || "ЗАГРУЗКА..."}
            </h1>
          </div>
          <p className="mt-4 text-xl text-zinc-500 font-medium uppercase tracking-tight">
            {profile?.role === "admin" ? "АДМИНИСТРАТОР" : "СОТРУДНИК"} {profile?.position ? `· ${profile.position}` : ""}
          </p>
        </div>
        <div className="grid gap-10 lg:grid-cols-12">
          <div className="lg:col-span-8 space-y-10">
            <div className="relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-10 shadow-2xl shadow-zinc-950/10 transition-all duration-300 hover:bg-white">
              <div className="absolute top-0 left-0 h-full w-[4px] bg-[#fe9900] opacity-25" />
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-8 mb-12">
                <h2 className="text-3xl font-black text-zinc-950 uppercase tracking-tighter leading-none">Лента активности</h2>
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-xl"
                  onClick={() => setHistoryOpen(true)}
                  disabled={loading || feed.length === 0}
                >
                  Вся история
                </Button>
              </div>

              <div className="space-y-4 max-h-[520px] overflow-y-auto pr-4 scrollbar-thin scrollbar-thumb-zinc-200">
                {feed.length === 0 ? (
                  <div className="py-20 text-center text-[10px] font-black uppercase tracking-widest text-zinc-600 border border-dashed border-zinc-200 rounded-[28px]">
                    Активность пока не зафиксирована
                  </div>
                ) : (
                  feed.map((it, idx) => (
                    <div key={idx} className="group relative overflow-hidden rounded-[24px] border border-zinc-200 bg-white/70 p-6 transition-all duration-300 hover:bg-white">
                      <div className="flex items-center justify-between gap-6">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-3">
                            <span className="h-1.5 w-1.5 rounded-full bg-[#fe9900]" />
                            <h4 className="truncate text-sm font-black text-zinc-950 uppercase tracking-widest transition-colors">
                              {it.title}
                            </h4>
                          </div>
                          {it.subtitle && <p className="mt-2 text-[10px] font-bold text-zinc-500 uppercase tracking-tight">{it.subtitle}</p>}
                          {it.kind === "quiz_attempt" && (
                            <div className="mt-4 flex items-center gap-4">
                              <span
                                className={`text-[9px] font-black uppercase tracking-widest px-2 py-1 rounded-md border ${
                                  it.passed
                                    ? "bg-[#284e13]/10 text-[#284e13] border-[#284e13]/20"
                                    : "bg-rose-50 text-rose-700 border-rose-200"
                                }`}
                              >
                                {it.status}
                              </span>
                              <span className="text-[10px] font-black text-zinc-600 tabular-nums uppercase">{it.score}%</span>
                              {it.duration_seconds && <span className="text-[10px] font-black text-zinc-600 uppercase tabular-nums">{formatDuration(it.duration_seconds)}</span>}
                            </div>
                          )}
                        </div>
                        <div className="text-right shrink-0">
                          <div className="text-[9px] font-black text-zinc-600 uppercase tracking-widest">{new Date(it.created_at).toLocaleDateString()}</div>
                          <div className="mt-1 text-[9px] font-black text-zinc-700 uppercase tabular-nums">{new Date(it.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          <div className="lg:col-span-4 space-y-10">
            <div className="relative overflow-hidden rounded-[28px] border border-zinc-200 bg-white/70 backdrop-blur-md p-8 shadow-2xl shadow-zinc-950/10">
              <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500 mb-8">Достижения</div>
              <div className="grid gap-3">
                {achievements.map((a) => (
                  <div
                    key={a.key}
                    className={`group relative p-4 rounded-2xl border transition-all duration-300 ${
                      a.done
                        ? "border-[#284e13]/20 bg-[#284e13]/5"
                        : "border-zinc-200 bg-white/70 opacity-50 grayscale"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="text-[10px] font-black text-zinc-950 uppercase tracking-widest">{a.title}</div>
                        <div className="mt-1 text-[9px] font-bold text-zinc-500 uppercase">{a.desc}</div>
                      </div>
                      {a.done && <div className="text-[#284e13] font-black">✓</div>}
                    </div>
                  </div>
                ))}
              </div>
            </div>

          </div>
        </div>
      </div>

      <Modal open={historyOpen} onClose={() => setHistoryOpen(false)}>
        <div className="w-[min(92vw,760px)]">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900]">АКТИВНОСТЬ</div>
              <div className="mt-1 text-2xl font-black tracking-tighter text-zinc-950 uppercase">Полная история</div>
            </div>
            <button
              type="button"
              onClick={() => setHistoryOpen(false)}
              className="h-10 w-10 rounded-xl border border-zinc-200 bg-white flex items-center justify-center hover:bg-zinc-50 transition-colors"
              aria-label="Закрыть"
            >
              <span className="text-xl font-light">×</span>
            </button>
          </div>

          <div className="mt-6 space-y-4">
            {(feed || []).length === 0 ? (
              <div className="py-16 text-center text-[10px] font-black uppercase tracking-widest text-zinc-600 border border-dashed border-zinc-200 rounded-[28px]">
                Активность пока не зафиксирована
              </div>
            ) : (
              <div className="space-y-4">
                {feed.map((it, idx) => (
                  <div key={idx} className="group relative overflow-hidden rounded-[24px] border border-zinc-200 bg-white/70 p-6 transition-all duration-300 hover:bg-white">
                    <div className="flex items-center justify-between gap-6">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-3">
                          <span className="h-1.5 w-1.5 rounded-full bg-[#fe9900]" />
                          <h4 className="truncate text-sm font-black text-zinc-950 uppercase tracking-widest transition-colors">
                            {it.title}
                          </h4>
                        </div>
                        {it.subtitle && <p className="mt-2 text-[10px] font-bold text-zinc-500 uppercase tracking-tight">{it.subtitle}</p>}
                        {it.kind === "quiz_attempt" && (
                          <div className="mt-4 flex items-center gap-4">
                            <span
                              className={`text-[9px] font-black uppercase tracking-widest px-2 py-1 rounded-md border ${
                                it.passed
                                  ? "bg-[#284e13]/10 text-[#284e13] border-[#284e13]/20"
                                  : "bg-rose-50 text-rose-700 border-rose-200"
                              }`}
                            >
                              {it.status}
                            </span>
                            <span className="text-[10px] font-black text-zinc-600 tabular-nums uppercase">{it.score}%</span>
                            {it.duration_seconds && <span className="text-[10px] font-black text-zinc-600 uppercase tabular-nums">{formatDuration(it.duration_seconds)}</span>}
                          </div>
                        )}
                      </div>
                      <div className="text-right shrink-0">
                        <div className="text-[9px] font-black text-zinc-600 uppercase tracking-widest">{new Date(it.created_at).toLocaleDateString()}</div>
                        <div className="mt-1 text-[9px] font-black text-zinc-700 uppercase tabular-nums">{new Date(it.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="mt-8">
            <Button className="w-full rounded-2xl" onClick={() => setHistoryOpen(false)}>
              Закрыть
            </Button>
          </div>
        </div>
      </Modal>
    </AppShell>
  );
}
