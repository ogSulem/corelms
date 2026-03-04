"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { apiFetch } from "@/lib/api";

type ModuleItem = {
  id: string;
  title: string;
  description: string | null;
  difficulty: number;
  category: string | null;
  is_active: boolean;
  progress: {
    read_count: number;
    total_lessons: number;
    passed_count: number;
    final_passed: boolean;
    completed: boolean;
  };
};

export default function ModulesPage() {
  const [items, setItems] = useState<ModuleItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const [query, setQuery] = useState("");

  const reloadInFlightRef = useRef(false);
  const lastReloadAtRef = useRef(0);

  async function reload(opts?: { force?: boolean }) {
    const now = Date.now();
    if (reloadInFlightRef.current) return;
    if (!opts?.force && now - Number(lastReloadAtRef.current || 0) < 2500) return;
    reloadInFlightRef.current = true;
    lastReloadAtRef.current = now;
    try {
      setError(null);
      if (items.length === 0) setLoading(true);
      else setIsRefreshing(true);
      const resp = await apiFetch<{ items: ModuleItem[] }>("/modules/overview");
      setItems(resp.items || []);
    } catch (e) {
      const anyErr = e as any;
      const msg = e instanceof Error ? e.message : "Не удалось загрузить список модулей";
      const rid = String(anyErr?.requestId || anyErr?.request_id || "").trim();
      setError((msg || "Не удалось загрузить список модулей") + (rid ? ` (код: ${rid})` : ""));
    } finally {
      setLoading(false);
      setIsRefreshing(false);
      reloadInFlightRef.current = false;
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  useEffect(() => {
    let es: EventSource | null = null;
    let stopped = false;
    let backoffMs = 800;
    const backoffMaxMs = 15_000;
    let reconnectTimer: number | null = null;
    let lastRev = 0;

    const clearReconnect = () => {
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    };

    const scheduleReconnect = (why: string) => {
      if (stopped) return;
      clearReconnect();
      const jitter = Math.floor(Math.random() * 250);
      const delay = Math.min(backoffMaxMs, Math.max(250, backoffMs + jitter));
      backoffMs = Math.min(backoffMaxMs, Math.floor(backoffMs * 1.6));
      reconnectTimer = window.setTimeout(() => open("reconnect:" + why), delay);
    };

    const close = (why: string) => {
      try {
        es?.close();
      } catch {
        // ignore
      }
      es = null;
    };

    const open = (why: string) => {
      if (stopped) return;
      clearReconnect();
      close("reopen");
      try {
        es = new EventSource("/api/backend/modules/events");
      } catch {
        es = null;
        scheduleReconnect("ctor_fail");
        return;
      }

      es.addEventListener("error", () => {
        close("error");
        scheduleReconnect("error");
      });

      es.addEventListener("modules", (ev: MessageEvent) => {
        try {
          const payload = JSON.parse(String((ev as any)?.data || "{}")) as any;
          const rev = Number(payload?.rev || 0);
          if (rev && rev <= lastRev) return;
          if (rev) lastRev = rev;
        } catch {
          // ignore
        }
        void reload({ force: true });
      });
    };

    open("mount");
    return () => {
      stopped = true;
      clearReconnect();
      close("unmount");
    };
  }, []);

  useEffect(() => {
    const onUpdated = () => {
      void reload();
    };
    window.addEventListener("corelms:modules-updated", onUpdated as EventListener);
    return () => window.removeEventListener("corelms:modules-updated", onUpdated as EventListener);
  }, []);

  useEffect(() => {
    const onRefresh = (e: any) => {
      try {
        const reason = String(e?.detail?.reason || "").trim().toLowerCase();
        if (reason === "keepalive") return;
        if (reason === "progress") {
          void reload({ force: true });
          return;
        }
      } catch {
        // ignore
      }
      void reload();
    };
    const onStorage = (e: StorageEvent) => {
      if (e.key === "corelms:modules-updated") {
        void reload();
      }
    };
    let lastHiddenAt = 0;
    const onFocus = () => void reload();
    const onVisibility = () => {
      const st = document.visibilityState;
      if (st === "hidden") {
        lastHiddenAt = Date.now();
        return;
      }
      if (st === "visible") {
        const hiddenForMs = lastHiddenAt ? Date.now() - lastHiddenAt : 0;
        if (hiddenForMs >= 30_000) {
          void reload();
        }
      }
    };

    window.addEventListener("storage", onStorage);
    window.addEventListener("focus", onFocus);
    window.addEventListener("corelms:refresh-me", onRefresh as EventListener);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("corelms:refresh-me", onRefresh as EventListener);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  const filteredItems = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (items || []).filter((m) => {
      if (!q) return true;
      const hay = `${m.title} ${m.description || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [items, query]);

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-6 py-10">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900]">Обучение</div>
            <h1 className="mt-2 text-4xl font-black tracking-tighter text-zinc-950 uppercase">Модули</h1>
          </div>
        </div>

        {error && (
          <div className="mt-6 rounded-2xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
            {error}
          </div>
        )}

        <div className="mt-8 grid gap-4 rounded-[28px] border border-zinc-200 bg-white/70 backdrop-blur-md p-6 shadow-2xl shadow-zinc-950/10 md:grid-cols-12">
          <div className="md:col-span-8">
            <div className="text-[9px] font-black uppercase tracking-widest text-zinc-600 ml-1">Поиск</div>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Название или описание"
              className="mt-2 h-12 w-full rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-black uppercase tracking-widest text-zinc-950 outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15"
            />
          </div>

          <div className="md:col-span-12 flex flex-wrap items-center justify-between gap-3 pt-2">
            <div className="text-[9px] font-black uppercase tracking-widest text-zinc-600">
              Показано: {loading ? "..." : String(filteredItems.length)}
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                className={`h-10 rounded-xl font-black uppercase tracking-widest text-[9px] transition-all ${isRefreshing ? "opacity-50" : ""}`}
                disabled={loading || isRefreshing}
                onClick={() => void reload()}
              >
                {isRefreshing ? (
                  <div className="flex items-center gap-2">
                    <div className="h-3 w-3 animate-spin rounded-full border-2 border-zinc-400 border-t-transparent" />
                    ОБНОВЛЕНИЕ
                  </div>
                ) : "ОБНОВИТЬ"}
              </Button>
            </div>
          </div>
        </div>

        <div className="mt-8 grid gap-6 md:grid-cols-2">
          {loading
            ? Array.from({ length: 6 }).map((_, idx) => (
                <Card
                  key={`sk_${idx}`}
                  className="h-full overflow-hidden border border-zinc-200 bg-white/70"
                >
                  <CardHeader className="pb-3">
                    <div className="h-5 w-3/5 animate-pulse rounded bg-zinc-200" />
                    <div className="mt-3 h-4 w-full animate-pulse rounded bg-zinc-100" />
                    <div className="mt-2 h-4 w-4/5 animate-pulse rounded bg-zinc-100" />
                  </CardHeader>
                  <CardContent>
                    <div className="mt-1 h-24 animate-pulse rounded-xl bg-zinc-100" />
                  </CardContent>
                </Card>
              ))
            : filteredItems.map((m) => (
            <Card
              key={m.id}
              className="group relative overflow-hidden rounded-[28px] border border-zinc-200 bg-white/70 p-1 transition-all duration-300 hover:bg-white"
            >
                <div className="absolute left-0 top-0 h-full w-[4px] bg-[#fe9900] opacity-0 group-hover:opacity-100 transition-opacity" />
                <CardHeader className="p-8 pb-4">
                  <div className="flex items-start justify-between gap-4">
                    <CardTitle className="text-2xl font-black text-zinc-950 transition-colors leading-tight tracking-tighter">
                      {m.title.toUpperCase()}
                    </CardTitle>
                    <div
                      className={
                        "shrink-0 rounded-full px-4 py-1.5 text-[10px] font-black uppercase tracking-widest " +
                        (m.progress?.completed
                          ? "bg-[#284e13]/10 text-[#284e13] border border-[#284e13]/20"
                          : "bg-zinc-100 text-zinc-600 border border-zinc-200")
                      }
                    >
                      {m.progress?.completed ? "ЗАВЕРШЕНО" : "В ПРОЦЕССЕ"}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="px-8 pb-8 pt-0 text-sm">
                  {m.description ? (
                    <div className="text-zinc-600 font-medium leading-relaxed line-clamp-2 min-h-[3rem]">
                      {m.description}
                    </div>
                  ) : null}

                  {m.progress ? (
                    <div className="mt-10 space-y-4">
                      <div className="flex items-center justify-between text-[10px] font-black uppercase tracking-[0.2em] text-zinc-600">
                        <span>Аттестация</span>
                        <span className="text-zinc-950 tabular-nums">
                          {m.progress.passed_count} / {m.progress.total_lessons}
                        </span>
                      </div>
                      <div className="h-1.5 w-full rounded-full bg-zinc-200 overflow-hidden">
                        <div 
                          className="h-full bg-[#fe9900] transition-all duration-1000"
                          style={{
                            width: `${m.progress.total_lessons > 0
                              ? Math.round((m.progress.passed_count / m.progress.total_lessons) * 100)
                              : 0}%`
                          }}
                        />
                      </div>
                    </div>
                  ) : null}

                  <div className="mt-10">
                    <Link href={`/modules/${m.id}`}>
                      <Button className="w-full h-14 rounded-2xl" variant={m.progress?.completed ? "outline" : "primary"}>
                        {m.progress?.completed ? "Повторить" : "Продолжить"}
                      </Button>
                    </Link>
                  </div>
                </CardContent>
            </Card>
          ))}
        </div>

        {!loading && filteredItems.length === 0 ? (
          <div className="mt-10 rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-12 text-center shadow-2xl shadow-zinc-950/10">
            <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900] mb-4">Контент</div>
            <div className="text-2xl font-black tracking-tighter text-zinc-950 uppercase">Модулей пока нет</div>
            <div className="mt-4 text-sm text-zinc-600 font-medium uppercase tracking-tight">
              Добавьте первый модуль через админ‑центр (импорт ZIP).
            </div>
            <div className="mt-8">
              <Link href="/adminpanel">
                <Button className="h-14 px-10 rounded-2xl">
                  Открыть админ‑центр
                </Button>
              </Link>
            </div>
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
