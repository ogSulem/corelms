"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, Loader2, RefreshCw, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";

type Totals = {
  users: number; employees: number; partners?: number; admins: number; active_7d: number;
  modules: number; published: number; drafts: number; archived: number;
  lessons: number; completions: number; attempts: number; pass_rate: number;
  events_total: number; events_30d: number;
  // Завершения считаются парами «человек × модуль», поэтому их больше, чем модулей.
  learners_completed?: number; modules_completed?: number; completion_rate?: number;
};

type ModuleRow = {
  id: string; title: string; is_active: boolean; is_archived: boolean; lesson_count: number;
  started: number; completed: number; in_progress: number; avg_percent: number;
  attempts: number; pass_rate: number; avg_score: number;
};

type UserRow = {
  id: string; name: string; email: string | null; role: string; position: string | null;
  started: number; completed: number; in_progress: number; avg_percent: number;
  attempts: number; avg_score: number; pass_rate: number; last_activity_at: string | null;
};

type Overview = { generated_at: string; totals: Totals; modules: ModuleRow[]; users: UserRow[] };

const btn = "gap-2 rounded-xl text-sm font-medium normal-case tracking-normal";
// employee и partner — одна и та же роль ученика: в интерфейсе её не раздваиваем.
const roleLabel: Record<string, string> = { employee: "Партнёр", partner: "Партнёр", admin: "Администратор", superadmin: "Суперадмин" };

function when(value: string | null): string {
  if (!value) return "не заходил";
  const days = Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000);
  if (days <= 0) return "сегодня";
  if (days === 1) return "вчера";
  if (days < 30) return `${days} дн. назад`;
  return new Date(value).toLocaleDateString("ru-RU");
}

function Kpi({ value, label, hint }: { value: string | number; label: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm">
      <p className="text-2xl font-semibold tabular-nums text-zinc-950">{value}</p>
      <p className="mt-1 text-xs font-medium text-zinc-700">{label}</p>
      {hint && <p className="mt-0.5 text-[11px] text-zinc-400">{hint}</p>}
    </div>
  );
}

function Bar({ percent, tone = "amber" }: { percent: number; tone?: "amber" | "emerald" }) {
  return (
    <div className="h-1.5 w-24 overflow-hidden rounded-full bg-zinc-100">
      <div className={`h-full rounded-full ${tone === "emerald" ? "bg-emerald-500" : "bg-amber-500"}`}
        style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} />
    </div>
  );
}

export function ResultsAdmin() {
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"modules" | "users">("modules");
  const [query, setQuery] = useState("");
  const [hideEmpty, setHideEmpty] = useState(true);
  const [sort, setSort] = useState<"default" | "started" | "completed" | "percent" | "attempts">("default");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await apiFetch<Overview>("/admin/analytics/overview");
      setData(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить результаты");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const needle = query.trim().toLocaleLowerCase("ru");

  const modules = useMemo(() => {
    const rows = (data?.modules || []).filter((m) => {
      if (m.is_archived) return false;
      if (hideEmpty && m.started === 0 && m.attempts === 0) return false;
      if (!needle) return true;
      return m.title.toLocaleLowerCase("ru").includes(needle);
    });
    if (sort === "started") return [...rows].sort((a, b) => b.started - a.started);
    if (sort === "completed") return [...rows].sort((a, b) => b.completed - a.completed);
    if (sort === "percent") return [...rows].sort((a, b) => b.avg_percent - a.avg_percent);
    if (sort === "attempts") return [...rows].sort((a, b) => b.attempts - a.attempts);
    return rows;
  }, [data, hideEmpty, needle, sort]);

  const users = useMemo(() => {
    const rows = (data?.users || []).filter((u) => {
      if (!needle) return true;
      return `${u.name} ${u.email || ""} ${u.position || ""}`.toLocaleLowerCase("ru").includes(needle);
    });
    if (sort === "started") return [...rows].sort((a, b) => b.started - a.started);
    if (sort === "completed") return [...rows].sort((a, b) => b.completed - a.completed);
    if (sort === "percent") return [...rows].sort((a, b) => b.avg_percent - a.avg_percent);
    if (sort === "attempts") return [...rows].sort((a, b) => b.attempts - a.attempts);
    return rows;
  }, [data, needle, sort]);

  const t = data?.totals;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Результаты обучения</h2>
          <p className="mt-1.5 text-sm text-zinc-500">
            Прогресс по модулям и по людям по одним правилам с кабинетом ученика.
            {data?.generated_at ? ` Данные на ${new Date(data.generated_at).toLocaleString("ru-RU")}.` : ""}
          </p>
        </div>
        <Button variant="outline" className={btn} onClick={() => void load()} disabled={loading}>
          {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}Обновить
        </Button>
      </div>

      {error && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</p>}

      {loading && !data ? (
        <div role="status" className="flex min-h-56 items-center justify-center gap-2 text-sm text-zinc-500">
          <Loader2 size={20} className="animate-spin" />Считаем результаты…
        </div>
      ) : t ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi value={t.users} label="Пользователей" hint={`заходили за неделю: ${t.active_7d}`} />
            <Kpi
              value={t.completions}
              label="Завершений модулей"
              hint={`у ${t.learners_completed ?? 0} сотрудников · охват ${t.modules_completed ?? 0} из ${t.published} модулей`}
            />
            <Kpi value={t.attempts} label="Попыток тестов" hint={`успешных: ${t.pass_rate}%`} />
            <Kpi value={`${t.events_30d}`} label="Событий за 30 дней" hint={`всего в журнале: ${t.events_total}`} />
          </div>

          <p className="rounded-xl border border-zinc-200 bg-white px-4 py-3 text-xs leading-6 text-zinc-600">
            Одно завершение = один сотрудник закончил один модуль, поэтому число завершений может быть
            больше числа модулей. Хотя бы один сотрудник закончил{" "}
            <span className="font-semibold text-zinc-900">{t.modules_completed ?? 0}</span> из{" "}
            <span className="font-semibold text-zinc-900">{t.published}</span> опубликованных модулей
            {typeof t.completion_rate === "number" ? ` · доводят до конца ${t.completion_rate}% начатого` : ""}.
          </p>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex gap-1 rounded-xl border border-zinc-200 bg-white p-1">
              {([{ id: "modules", label: `Модули · ${t.modules}` }, { id: "users", label: `Люди · ${t.users}` }] as const).map((tab) => (
                <button key={tab.id} type="button" aria-pressed={view === tab.id} onClick={() => { setView(tab.id); setSort("default"); }}
                  className={`rounded-lg px-3 py-2 text-xs font-medium ${view === tab.id ? "bg-amber-50 text-amber-900" : "text-zinc-500 hover:bg-zinc-50"}`}>
                  {tab.label}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 text-zinc-400">
                <Search size={16} />
                <input aria-label="Поиск" value={query} onChange={(e) => setQuery(e.target.value)}
                  placeholder={view === "modules" ? "Название модуля…" : "Имя или почта…"}
                  className="h-10 w-52 min-w-0 bg-transparent text-sm text-zinc-800 outline-none" />
              </label>
              <select aria-label="Сортировка" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}
                className="h-10 rounded-lg border border-zinc-200 bg-white px-3 text-xs text-zinc-700">
                <option value="default">По порядку</option>
                <option value="started">Больше начали</option>
                <option value="completed">Больше завершили</option>
                <option value="percent">Выше средний прогресс</option>
                <option value="attempts">Больше попыток</option>
              </select>
              {view === "modules" && (
                <label className="flex items-center gap-2 px-1 text-xs text-zinc-600">
                  <input type="checkbox" checked={hideEmpty} onChange={(e) => setHideEmpty(e.target.checked)} />
                  Скрыть без активности
                </label>
              )}
            </div>
          </div>

          {view === "modules" ? (
            <div className="overflow-x-auto rounded-2xl border border-zinc-200 bg-white shadow-sm">
              <table className="w-full min-w-[860px] text-sm">
                <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500">
                  <tr>
                    <th className="px-4 py-3 font-medium">Модуль</th>
                    <th className="px-4 py-3 font-medium">Начали</th>
                    <th className="px-4 py-3 font-medium">Завершили</th>
                    <th className="px-4 py-3 font-medium">Средний прогресс</th>
                    <th className="px-4 py-3 font-medium">Тесты</th>
                    <th className="px-4 py-3 font-medium" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100">
                  {modules.map((m) => (
                    <tr key={m.id} className="hover:bg-zinc-50/60">
                      <td className="px-4 py-3">
                        <p className="font-medium text-zinc-900">{m.title}</p>
                        <p className="text-xs text-zinc-500">
                          {m.lesson_count} уроков · {m.is_active ? "опубликован" : "черновик"}
                        </p>
                      </td>
                      <td className="px-4 py-3 tabular-nums text-zinc-800">{m.started}</td>
                      <td className="px-4 py-3 tabular-nums text-zinc-800">
                        {m.completed}
                        {m.started ? <span className="ml-1 text-xs text-zinc-400">({Math.round((m.completed / m.started) * 100)}%)</span> : null}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <Bar percent={m.avg_percent} tone={m.avg_percent >= 80 ? "emerald" : "amber"} />
                          <span className="tabular-nums text-zinc-700">{m.avg_percent}%</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-xs text-zinc-600">
                        {m.attempts ? `${m.attempts} попыток · сдали ${m.pass_rate}% · средний балл ${m.avg_score}` : "нет попыток"}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link href={`/admin/modules/${m.id}`} className="inline-flex items-center gap-1 text-xs font-medium text-amber-800 hover:underline">
                          Открыть<ArrowRight size={13} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!modules.length && (
                <p className="py-12 text-center text-sm text-zinc-500">
                  {needle ? "Ничего не найдено." : hideEmpty ? "Пока никто не начал обучение. Снимите «Скрыть без активности»." : "Модулей нет."}
                </p>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto rounded-2xl border border-zinc-200 bg-white shadow-sm">
              <table className="w-full min-w-[860px] text-sm">
                <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500">
                  <tr>
                    <th className="px-4 py-3 font-medium">Человек</th>
                    <th className="px-4 py-3 font-medium">Завершено</th>
                    <th className="px-4 py-3 font-medium">В работе</th>
                    <th className="px-4 py-3 font-medium">Средний прогресс</th>
                    <th className="px-4 py-3 font-medium">Тесты</th>
                    <th className="px-4 py-3 font-medium">Активность</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100">
                  {users.map((u) => (
                    <tr key={u.id} className="hover:bg-zinc-50/60">
                      <td className="px-4 py-3">
                        <p className="font-medium text-zinc-900">{u.name}</p>
                        <p className="text-xs text-zinc-500">
                          {roleLabel[u.role] || u.role}{u.position ? ` · ${u.position}` : ""}
                        </p>
                      </td>
                      <td className="px-4 py-3 tabular-nums text-zinc-800">{u.completed}</td>
                      <td className="px-4 py-3 tabular-nums text-zinc-800">{u.in_progress}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <Bar percent={u.avg_percent} tone={u.avg_percent >= 80 ? "emerald" : "amber"} />
                          <span className="tabular-nums text-zinc-700">{u.avg_percent}%</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-xs text-zinc-600">
                        {u.attempts ? `${u.attempts} · сдал ${u.pass_rate}% · балл ${u.avg_score}` : "—"}
                      </td>
                      <td className="px-4 py-3 text-xs text-zinc-600">{when(u.last_activity_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!users.length && <p className="py-12 text-center text-sm text-zinc-500">{needle ? "Ничего не найдено." : "Пользователей нет."}</p>}
            </div>
          )}

          <p className="text-xs leading-6 text-zinc-500">
            Прогресс считается по прочитанным урокам и сданным тестам. Достижения по модулю не отзываются при обновлении материалов:
            если модуль обновили, у завершивших он помечается как «есть обновления», но зачёт остаётся.
          </p>
        </>
      ) : null}
    </div>
  );
}
