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
  ip?: string | null;
  request_id?: string | null;
  module_id?: string | null;
  module_title?: string | null;
  submodule_id?: string | null;
  submodule_title?: string | null;
  asset_id?: string | null;
  asset_name?: string | null;
};

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m <= 0) return `${s}S`;
  return `${m}M ${s}S`;
}

export default function AccountPage() {
  const [profile, setProfile] = useState<MyProfile | null>(null);
  const [historyAll, setHistoryAll] = useState<HistoryItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);

  const securitySummary = useMemo(() => {
    const sec = (historyAll || []).filter((x) => x.kind === "security");
    const latest = sec.length ? sec[0] : null;
    const latestSubtitle = String(latest?.subtitle || "").trim();

    const newIpCount = sec.filter((x) => String(x.title || "").toLowerCase().includes("нового ip")).length;
    const newDevCount = sec.filter((x) => String(x.title || "").toLowerCase().includes("нового устройства")).length;

    return {
      latestSubtitle,
      newIpCount,
      newDevCount,
    };
  }, [historyAll]);

  useEffect(() => {
    (async () => {
      try {
        setError(null);
        setLoading(true);

        const p = await apiFetch<MyProfile>("/me/profile");
        setProfile(p);

        const hist = await apiFetch<{ items: HistoryItem[] }>(`/me/history?limit=200`);
        const items = Array.isArray(hist?.items) ? hist.items : [];
        setHistoryAll(items);
      } catch (e) {
        setError("НЕ УДАЛОСЬ ЗАГРУЗИТЬ ДАННЫЕ ПРОФИЛЯ");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const ipWidget = useMemo(() => {
    const sec = (historyAll || []).filter((x) => x.kind === "security");
    const seen: Array<{ ip: string; at: string }> = [];

    for (const it of sec) {
      const ip = String(it.ip || "")
        .trim()
        .replace(/^IP:\s*/i, "");
      const at = String(it.created_at || "").trim();
      if (!ip || !at) continue;
      seen.push({ ip, at });
    }

    const uniq: Array<{ ip: string; last_at: string }> = [];
    const map = new Map<string, string>();
    for (const s of seen) {
      const prev = map.get(s.ip);
      if (!prev || String(s.at) > String(prev)) {
        map.set(s.ip, s.at);
      }
    }
    for (const [ip, last_at] of map.entries()) {
      uniq.push({ ip, last_at });
    }
    uniq.sort((a, b) => String(b.last_at).localeCompare(String(a.last_at)));

    const current = uniq.length ? uniq[0] : null;
    const last5 = uniq.slice(0, 6);
    return { current, last5 };
  }, [historyAll]);

  const level = profile?.level ?? 1;
  const xp = profile?.xp ?? 0;
  const streak = profile?.streak ?? 0;
  const nextLevelXp = level * 100;
  const prevLevelXp = (level - 1) * 100;
  const inLevel = Math.max(0, xp - prevLevelXp);
  const levelSpan = Math.max(1, nextLevelXp - prevLevelXp);
  const levelProgress = Math.max(0, Math.min(100, Math.round((inLevel / levelSpan) * 100)));

  const achievements = useMemo(() => {
    const hasQuizAttempt = (historyAll || []).some((it) => it.kind === "quiz_attempt");
    const hasLesson = (historyAll || []).some((it) => it.kind === "lesson");
    const hasAsset = (historyAll || []).some((it) => it.kind === "asset");

    return [
      { key: "first_step", title: "ПЕРВЫЙ ШАГ", desc: "АКТИВНОСТЬ ЗАФИКСИРОВАНА", done: (historyAll || []).length > 0 },
      { key: "first_quiz", title: "ПЕРВЫЙ ТЕСТ", desc: "ПОПЫТКА ЗАСЧИТАНА", done: hasQuizAttempt },
      { key: "streak_3", title: "СТРИК 3", desc: "РИТМ СОЗДАН", done: streak >= 3 },
      { key: "streak_7", title: "СТРИК 7", desc: "ПРИВЫЧКА СФОРМИРОВАНА", done: streak >= 7 },
      { key: "xp_100", title: "100 XP", desc: "ПРОГРЕСС РАСТЁТ", done: xp >= 100 },
      { key: "lvl_5", title: "УРОВЕНЬ 5", desc: "ВЫШЕ КВАЛИФИКАЦИЯ", done: level >= 5 },
    ];
  }, [historyAll, level, streak, xp]);

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
            <div className="min-w-0">
              <h1 className="text-5xl font-black tracking-tighter text-zinc-950 uppercase leading-none truncate">
                {profile?.name || "ЗАГРУЗКА..."}
              </h1>
              {securitySummary.latestSubtitle ? (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <div className="rounded-full border border-zinc-200 bg-white px-3 py-1 text-[10px] font-black uppercase tracking-widest text-zinc-700">
                    {securitySummary.latestSubtitle}
                  </div>
                  {securitySummary.newIpCount > 0 ? (
                    <div className="rounded-full border border-[#fe9900]/25 bg-[#fe9900]/10 px-3 py-1 text-[10px] font-black uppercase tracking-widest text-zinc-900">
                      НОВЫЙ IP · {securitySummary.newIpCount}
                    </div>
                  ) : null}
                  {securitySummary.newDevCount > 0 ? (
                    <div className="rounded-full border border-[#fe9900]/25 bg-[#fe9900]/10 px-3 py-1 text-[10px] font-black uppercase tracking-widest text-zinc-900">
                      НОВОЕ УСТРОЙСТВО · {securitySummary.newDevCount}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>

            <div className="w-full lg:w-[360px]">
              <div className="rounded-[28px] border border-zinc-200 bg-white/70 backdrop-blur-md p-6 shadow-2xl shadow-zinc-950/10">
                <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">IP</div>
                <div className="mt-3">
                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Текущий</div>
                  <div className="mt-1 text-sm font-black text-zinc-950 tabular-nums">
                    {ipWidget.current?.ip || "—"}
                  </div>
                  {ipWidget.current?.last_at ? (
                    <div className="mt-1 text-[10px] font-bold text-zinc-500 tabular-nums">
                      {new Date(ipWidget.current.last_at).toLocaleString("ru-RU", {
                        day: "2-digit",
                        month: "2-digit",
                        year: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </div>
                  ) : null}
                </div>

                <div className="mt-5">
                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Последние 5</div>
                  <div className="mt-2 space-y-2">
                    {ipWidget.last5.length ? (
                      ipWidget.last5.slice(0, 5).map((x) => (
                        <div key={x.ip} className="flex items-center justify-between gap-3">
                          <div className="text-[10px] font-black text-zinc-950 tabular-nums">{x.ip}</div>
                          <div className="text-[10px] font-bold text-zinc-500 tabular-nums shrink-0">
                            {new Date(x.last_at).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" })}
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="text-[10px] font-bold text-zinc-500">—</div>
                    )}
                  </div>
                </div>
              </div>
            </div>
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
                <h2 className="text-3xl font-black text-zinc-950 uppercase tracking-tighter leading-none">История</h2>
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-xl"
                  onClick={() => setHistoryOpen(true)}
                  disabled={loading || historyAll.length === 0}
                >
                  Вся история
                </Button>
              </div>

              <div className="space-y-4 max-h-[520px] overflow-y-auto pr-4 scrollbar-thin scrollbar-thumb-zinc-200">
                {historyAll.length === 0 ? (
                  <div className="py-20 text-center text-[10px] font-black uppercase tracking-widest text-zinc-600 border border-dashed border-zinc-200 rounded-[28px]">
                    История пока пуста
                  </div>
                ) : (
                  (historyAll || []).slice(0, 20).map((h) => (
                    <div
                      key={h.id}
                      className="group rounded-2xl border border-zinc-100 bg-zinc-50/50 p-4 transition-all hover:bg-white hover:border-[#fe9900]/20 hover:shadow-xl hover:shadow-zinc-950/5"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="space-y-1 min-w-0">
                          <div className="text-[11px] font-black text-zinc-950 uppercase tracking-tight truncate">
                            {h.title}
                          </div>
                          {h.subtitle ? (
                            <div className="text-[10px] text-zinc-500 font-bold uppercase tracking-tight truncate">
                              {h.subtitle}
                            </div>
                          ) : null}
                          {(h.module_title || h.submodule_title || h.asset_name || h.ip) ? (
                            <div className="text-[10px] text-zinc-500 font-bold uppercase tracking-tight">
                              {[h.module_title, h.submodule_title, h.asset_name, h.ip ? `IP: ${h.ip}` : null]
                                .filter(Boolean)
                                .join(" · ")}
                            </div>
                          ) : null}
                          <div className="text-[10px] text-zinc-500 font-bold tabular-nums">
                            {new Date(h.created_at).toLocaleString("ru-RU", {
                              day: "2-digit",
                              month: "2-digit",
                              year: "numeric",
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </div>
                        </div>
                        {h.meta ? (
                          <div className="rounded-lg border border-zinc-200 bg-white px-2 py-1 text-[9px] font-black text-zinc-600 uppercase">
                            META
                          </div>
                        ) : null}
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
            {(historyAll || []).length === 0 ? (
              <div className="py-16 text-center text-[10px] font-black uppercase tracking-widest text-zinc-600 border border-dashed border-zinc-200 rounded-[28px]">
                История пока пуста
              </div>
            ) : (
              <div className="space-y-4">
                {(historyAll || []).map((h) => (
                  <div
                    key={h.id}
                    className="group rounded-2xl border border-zinc-100 bg-zinc-50/50 p-4 transition-all hover:bg-white hover:border-[#fe9900]/20 hover:shadow-xl hover:shadow-zinc-950/5"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="space-y-1 min-w-0">
                        <div className="text-[11px] font-black text-zinc-950 uppercase tracking-tight truncate">{h.title}</div>
                        {h.subtitle ? (
                          <div className="text-[10px] text-zinc-500 font-bold uppercase tracking-tight truncate">{h.subtitle}</div>
                        ) : null}
                        {(h.module_title || h.submodule_title || h.asset_name || h.ip) ? (
                          <div className="text-[10px] text-zinc-500 font-bold uppercase tracking-tight">
                            {[h.module_title, h.submodule_title, h.asset_name, h.ip ? `IP: ${h.ip}` : null]
                              .filter(Boolean)
                              .join(" · ")}
                          </div>
                        ) : null}
                        <div className="text-[10px] text-zinc-500 font-bold tabular-nums">
                          {new Date(h.created_at).toLocaleString("ru-RU", {
                            day: "2-digit",
                            month: "2-digit",
                            year: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </div>
                      </div>
                      {h.meta ? (
                        <div className="rounded-lg border border-zinc-200 bg-white px-2 py-1 text-[9px] font-black text-zinc-600 uppercase">
                          META
                        </div>
                      ) : null}
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
