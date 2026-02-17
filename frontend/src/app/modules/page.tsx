"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

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

  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"all" | "in_progress" | "completed">("all");
  const [category, setCategory] = useState<string>("all");

  async function reload() {
    try {
      setError(null);
      setLoading(true);
      const resp = await apiFetch<{ items: ModuleItem[] }>("/modules/overview");
      setItems(resp.items || []);
    } catch (e) {
      const anyErr = e as any;
      const msg = e instanceof Error ? e.message : "Не удалось загрузить список модулей";
      const rid = String(anyErr?.requestId || anyErr?.request_id || "").trim();
      setError((msg || "Не удалось загрузить список модулей") + (rid ? ` (код: ${rid})` : ""));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  useEffect(() => {
    const onUpdated = () => {
      void reload();
    };
    window.addEventListener("corelms:modules-updated", onUpdated as EventListener);
    return () => window.removeEventListener("corelms:modules-updated", onUpdated as EventListener);
  }, []);

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === "corelms:modules-updated") {
        void reload();
      }
    };
    const onFocus = () => {
      void reload();
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        void reload();
      }
    };

    window.addEventListener("storage", onStorage);
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  const categories = useMemo(() => {
    const s = new Set<string>();
    (items || []).forEach((m) => {
      if (m.category) s.add(m.category);
    });
    return Array.from(s).sort((a, b) => a.localeCompare(b));
  }, [items]);

  const filteredItems = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (items || []).filter((m) => {
      if (status === "completed" && !m.progress?.completed) return false;
      if (status === "in_progress" && m.progress?.completed) return false;
      if (category !== "all" && (m.category || "") !== category) return false;
      if (!q) return true;
      const hay = `${m.title} ${m.description || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [category, items, query, status]);

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
