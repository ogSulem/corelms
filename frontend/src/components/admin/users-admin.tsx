"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Check, Copy, KeyRound, Loader2, Plus, RefreshCw, Search, ShieldCheck,
  Tags, Trash2, UserRound, Users, X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { apiFetch } from "@/lib/api";
import { isAdminRole, isEmployeeRole, matchesRoleTab, type AdminRole, type RoleTab } from "@/lib/admin-users-filter";
import { throttleRefresh } from "@/lib/refresh-throttle";
import { useAuth } from "@/lib/hooks/use-auth";

// partner встречается в рабочих данных: роль без административных прав.
type Role = AdminRole;

type ProgressSummary = {
  completed_count: number;
  in_progress_count: number;
  current: { module_id: string; title: string; total: number; passed: number; percent: number } | null;
};

type AdminUser = {
  id: string;
  name: string;
  email?: string | null;
  role: Role;
  position?: string | null;
  xp: number;
  level: number;
  streak: number;
  last_activity_at: string | null;
  created_at: string | null;
  progress_summary: ProgressSummary;
  tag_ids: string[];
  tags: string[];
};

type ModuleProgress = { module_id: string; title: string; total: number; passed: number; percent: number; completed?: boolean };

type UserDetail = {
  stats?: { assignments_total: number; assignments_completed: number; attempts_total: number; attempts_passed: number; events_total: number };
  modules_progress?: {
    completed: ModuleProgress[];
    in_progress: ModuleProgress[];
    overall_progress: { steps_total: number; steps_completed: number; percent: number };
  };
};

type TagItem = { id: string; name: string };

const btn = "gap-2 rounded-xl text-sm font-medium normal-case tracking-normal";
const field = "w-full rounded-xl border border-zinc-200 px-3.5 py-2.5 text-sm text-zinc-900 outline-none focus:border-amber-500";
const roleLabel: Record<Role, string> = {
  // employee и partner — одна и та же роль без прав администратора, поэтому
  // в интерфейсе она называется одинаково. Значение в базе не переписываем:
  // старые записи остаются employee, но выглядят и ведут себя как партнёр.
  employee: "Партнёр",
  partner: "Партнёр",
  admin: "Администратор",
  superadmin: "Суперадмин",
};

/** Роль для выбора в карточке: employee и partner — одно и то же. */
function learnerRole(role: Role): Role {
  return role === "employee" ? "partner" : role;
}

function when(value: string | null): string {
  if (!value) return "не заходил";
  const date = new Date(value);
  const days = Math.floor((Date.now() - date.getTime()) / 86_400_000);
  if (days <= 0) return "сегодня";
  if (days === 1) return "вчера";
  if (days < 30) return `${days} дн. назад`;
  return date.toLocaleDateString("ru-RU");
}

function toast(title: string, description = "") {
  window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title, description } }));
}

export function UsersAdmin() {
  const { user: me } = useAuth();
  const isSuperadmin = me?.role === "superadmin";
  const [items, setItems] = useState<AdminUser[]>([]);
  const [tags, setTags] = useState<TagItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState<RoleTab>("all");
  const [onlyActive, setOnlyActive] = useState(false);
  const [busy, setBusy] = useState(false);

  const [selected, setSelected] = useState<AdminUser | null>(null);
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [draft, setDraft] = useState({ name: "", email: "", position: "", role: "employee" as Role });
  const [selectedTags, setSelectedTags] = useState<string[]>([]);

  const [tagsOpen, setTagsOpen] = useState(false);
  const [newTagName, setNewTagName] = useState("");
  const [creating, setCreating] = useState(false);
  const [newUser, setNewUser] = useState({ name: "", email: "", position: "" });
  const [tempPassword, setTempPassword] = useState<{ name: string; password: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const request = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    try {
      const [users, tagList] = await Promise.all([
        apiFetch<{ items: AdminUser[] }>("/admin/users", { signal: controller.signal }),
        apiFetch<{ items: TagItem[] }>("/admin/tags", { signal: controller.signal }).catch(() => ({ items: [] })),
      ]);
      if (controller.signal.aborted) return;
      setItems(users.items || []);
      setTags(tagList.items || []);
      setError(null);
    } catch (e) {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Не удалось загрузить пользователей");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    // Возврат на вкладку не должен каждый раз перерисовывать таблицу:
    // обновляем не чаще раза в минуту, кнопка «Обновить» работает всегда.
    const focus = throttleRefresh(() => void load());
    window.addEventListener("focus", focus);
    return () => { request.current?.abort(); window.removeEventListener("focus", focus); };
  }, [load]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("ru");
    return items.filter((u) => {
      if (!matchesRoleTab(u.role, roleFilter)) return false;
      if (onlyActive && !u.last_activity_at) return false;
      if (!needle) return true;
      return `${u.name} ${u.email || ""} ${u.position || ""} ${u.tags.join(" ")}`
        .toLocaleLowerCase("ru").includes(needle);
    });
  }, [items, onlyActive, query, roleFilter]);

  const counters = useMemo(() => ({
    all: items.length,
    partners: items.filter((u) => isEmployeeRole(u.role)).length,
    admins: items.filter((u) => isAdminRole(u.role)).length,
  }), [items]);

  // «Сотрудники» и «Партнёры» были одним и тем же списком — оставляем одну вкладку.
  const tabs = useMemo(() => ([
    { id: "all" as RoleTab, label: "Все", count: counters.all },
    { id: "partner" as RoleTab, label: "Партнёры", count: counters.partners },
    { id: "admins" as RoleTab, label: "Администраторы", count: counters.admins },
  ]), [counters]);


  async function openUser(target: AdminUser) {
    setSelected(target);
    setDetail(null);
    setDraft({ name: target.name, email: target.email || "", position: target.position || "", role: learnerRole(target.role) });
    setSelectedTags(target.tag_ids || []);
    setDetailLoading(true);
    try {
      const data = await apiFetch<UserDetail>(`/admin/users/${target.id}`);
      setDetail(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось открыть карточку");
    } finally {
      setDetailLoading(false);
    }
  }

  async function saveUser() {
    if (!selected || busy) return;
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { name: draft.name.trim(), email: draft.email.trim(), position: draft.position.trim() };
      // Роль отправляем только когда её действительно поменяли: иначе открытие
      // и сохранение карточки молча переписывало бы employee на partner.
      if (isSuperadmin && draft.role !== learnerRole(selected.role)) body.role = draft.role;
      await apiFetch(`/admin/users/${selected.id}`, { method: "PATCH", body: JSON.stringify(body) });
      await apiFetch(`/admin/users/${selected.id}/tags`, { method: "PUT", body: JSON.stringify({ tag_ids: selectedTags }) });
      toast("Сохранено", "Изменения уже действуют");
      setSelected(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сохранить пользователя");
    } finally {
      setBusy(false);
    }
  }

  async function resetPassword() {
    if (!selected || busy) return;
    if (!window.confirm(`Сбросить пароль пользователю «${selected.name}»? Старый пароль перестанет работать.`)) return;
    setBusy(true);
    setError(null);
    try {
      const result = await apiFetch<{ temp_password: string }>(`/admin/users/${selected.id}/reset-password`, {
        method: "POST",
        body: JSON.stringify({ must_change_password: true }),
      });
      setTempPassword({ name: selected.name, password: result.temp_password });
      setCopied(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сбросить пароль");
    } finally {
      setBusy(false);
    }
  }

  async function deleteUser() {
    if (!selected || busy) return;
    if (!window.confirm(`Удалить «${selected.name}»? Вместе с ним удалятся его попытки тестов и история обучения. Это необратимо.`)) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/admin/users/${selected.id}`, { method: "DELETE" });
      toast("Пользователь удалён");
      setSelected(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось удалить пользователя");
    } finally {
      setBusy(false);
    }
  }

  async function createUser() {
    if (busy) return;
    if (!newUser.name.trim() || !newUser.email.trim()) {
      setError("Нужны имя и почта — по почте человек входит в систему");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await apiFetch<{ id: string; temp_password: string }>("/admin/users", {
        method: "POST",
        body: JSON.stringify({
          name: newUser.name.trim(),
          email: newUser.email.trim(),
          position: newUser.position.trim() || null,
          must_change_password: true,
        }),
      });
      setCreating(false);
      setNewUser({ name: "", email: "", position: "" });
      setTempPassword({ name: newUser.name.trim(), password: result.temp_password });
      setCopied(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось создать пользователя");
    } finally {
      setBusy(false);
    }
  }

  async function createTag() {
    const name = newTagName.trim();
    if (!name || busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await apiFetch<TagItem>("/admin/tags", { method: "POST", body: JSON.stringify({ name }) });
      setTags((prev) => (prev.some((t) => t.id === created.id) ? prev : [...prev, created].sort((a, b) => a.name.localeCompare(b.name, "ru"))));
      setNewTagName("");
      toast("Тег создан", `«${created.name}» появился в карточке каждого сотрудника`);
    } catch (e) {
      setError(e instanceof Error ? `Не удалось создать тег: ${e.message}` : "Не удалось создать тег");
    } finally {
      setBusy(false);
    }
  }

  async function deleteTag(tag: TagItem) {
    if (busy) return;
    if (!window.confirm(`Удалить тег «${tag.name}»? Он снимется со всех сотрудников и модулей.`)) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/admin/tags/${tag.id}`, { method: "DELETE" });
      setTags((prev) => prev.filter((t) => t.id !== tag.id));
      setSelectedTags((prev) => prev.filter((id) => id !== tag.id));
      await load();
      toast("Тег удалён", `«${tag.name}» больше никому не выдаётся`);
    } catch (e) {
      setError(e instanceof Error ? `Не удалось удалить тег: ${e.message}` : "Не удалось удалить тег");
    } finally {
      setBusy(false);
    }
  }

  async function copyPassword() {
    if (!tempPassword) return;
    try {
      await navigator.clipboard.writeText(tempPassword.password);
      setCopied(true);
    } catch {
      setError("Браузер не дал скопировать. Выделите пароль вручную.");
    }
  }

  // Правила те же, что на сервере (PATCH /admin/users/{id}): суперадмин правит
  // всех, обычный админ — сотрудников и себя, но не других администраторов.
  const canEditSelected = isSuperadmin || !selected || selected.id === me?.id || isEmployeeRole(selected.role);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Пользователи</h2>
          <p className="mt-1.5 text-sm text-zinc-500">
            Всего {counters.all}: партнёров {counters.partners}, администраторов {counters.admins}.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" className={btn} onClick={() => { setError(null); void load(); }}>
            <RefreshCw size={16} />Обновить
          </Button>
          <Button variant="outline" className={btn} onClick={() => { setError(null); setTagsOpen(true); }}>
            <Tags size={16} />Теги{tags.length ? <span className="text-xs text-zinc-400">{tags.length}</span> : null}
          </Button>
          <Button className={btn} onClick={() => { setError(null); setCreating(true); }}>
            <Plus size={16} />Добавить
          </Button>
        </div>
      </div>

      {error && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</p>}

      <div className="rounded-2xl border border-zinc-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200 p-4">
          <div className="flex flex-wrap gap-1">
            {(tabs).map((tab) => (
              <button key={tab.id} type="button" aria-pressed={roleFilter === tab.id} onClick={() => setRoleFilter(tab.id)}
                className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium ${roleFilter === tab.id ? "bg-amber-50 text-amber-900" : "text-zinc-500 hover:bg-zinc-50"}`}>
                {tab.label}<span className="text-[10px] opacity-60">{tab.count}</span>
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 rounded-lg border border-zinc-200 px-3 text-zinc-400">
              <Search size={16} />
              <input aria-label="Поиск пользователей" value={query} onChange={(e) => setQuery(e.target.value)}
                placeholder="Имя, почта, должность, тег…" className="h-10 w-56 min-w-0 bg-transparent text-sm text-zinc-800 outline-none" />
            </label>
            <label className="flex items-center gap-2 px-1 text-xs text-zinc-600">
              <input type="checkbox" checked={onlyActive} onChange={(e) => setOnlyActive(e.target.checked)} />
              Только заходившие
            </label>
          </div>
        </div>

        {loading ? (
          <div role="status" className="flex min-h-56 items-center justify-center gap-2 text-sm text-zinc-500">
            <Loader2 size={20} className="animate-spin" />Загружаем пользователей…
          </div>
        ) : filtered.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="px-4 py-3 font-medium">Пользователь</th>
                  <th className="px-4 py-3 font-medium">Роль</th>
                  <th className="px-4 py-3 font-medium">Прогресс</th>
                  <th className="px-4 py-3 font-medium">Активность</th>
                  <th className="px-4 py-3 font-medium" />
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {filtered.map((u) => (
                  <tr key={u.id} className="hover:bg-zinc-50/60">
                    <td className="px-4 py-3">
                      <p className="font-medium text-zinc-900">{u.name}{u.id === me?.id && <span className="ml-2 text-xs text-zinc-400">это вы</span>}</p>
                      <p className="text-xs text-zinc-500">{u.email || "почта не указана"}{u.position ? ` · ${u.position}` : ""}</p>
                      {!!u.tags.length && (
                        <p className="mt-1 flex flex-wrap gap-1">{u.tags.map((tag) => (
                          <span key={tag} className="rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] text-zinc-600">{tag}</span>
                        ))}</p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
                        u.role === "admin" || u.role === "superadmin" ? "bg-amber-50 text-amber-800" : "bg-zinc-100 text-zinc-600"
                      }`}>
                        {roleLabel[u.role] ?? u.role}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <p className="text-zinc-800">Завершено {u.progress_summary.completed_count} · в работе {u.progress_summary.in_progress_count}</p>
                      <p className="text-xs text-zinc-500">{u.progress_summary.current ? `Сейчас: ${u.progress_summary.current.title} — ${u.progress_summary.current.percent}%` : "Пока не начинал"}</p>
                    </td>
                    <td className="px-4 py-3 text-zinc-600">{when(u.last_activity_at)}</td>
                    <td className="px-4 py-3 text-right">
                      <Button variant="ghost" size="sm" className={btn} onClick={() => void openUser(u)}>Открыть</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-16 text-center">
            <Users size={34} className="mx-auto mb-3 text-zinc-300" />
            <p className="text-sm font-medium text-zinc-700">{query || roleFilter !== "all" || onlyActive ? "Никого не нашли" : "Пользователей пока нет"}</p>
            <p className="mt-1 text-xs text-zinc-500">{query || roleFilter !== "all" || onlyActive ? "Измените поиск или фильтр." : "Добавьте первого сотрудника кнопкой «Добавить»."}</p>
          </div>
        )}
      </div>

      <Modal open={!!selected} title={selected ? `${selected.name}` : ""} onClose={() => { if (!busy) setSelected(null); }} disableClose={busy} className="max-w-3xl"
        footer={<div className="flex flex-wrap justify-between gap-2">
          <Button variant="ghost" className={`${btn} text-rose-600`}
            disabled={busy || selected?.id === me?.id || (!isSuperadmin && !isEmployeeRole(selected?.role || ""))}
            title={!isSuperadmin && !isEmployeeRole(selected?.role || "") ? "Удалять администраторов может только суперадмин" : undefined}
            onClick={() => void deleteUser()}>
            <Trash2 size={15} />Удалить
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" className={btn} disabled={busy} onClick={() => void resetPassword()}><KeyRound size={15} />Сбросить пароль</Button>
            <Button className={btn} disabled={busy || !canEditSelected} title={canEditSelected ? undefined : "Изменять администраторов может только суперадмин"}
              onClick={() => void saveUser()}>{busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}Сохранить</Button>
          </div>
        </div>}>
        {selected && (
          <div className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block space-y-1.5 text-sm font-medium">Имя
                <input className={field} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              </label>
              <label className="block space-y-1.5 text-sm font-medium">Почта (логин)
                <input className={field} value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} placeholder="name@company.ru" />
              </label>
              <label className="block space-y-1.5 text-sm font-medium">Должность
                <input className={field} value={draft.position} onChange={(e) => setDraft({ ...draft, position: e.target.value })} />
              </label>
              <label className="block space-y-1.5 text-sm font-medium">Роль
                <select className={field} value={draft.role} disabled={!isSuperadmin || selected.id === me?.id}
                  onChange={(e) => setDraft({ ...draft, role: e.target.value as Role })}>
                  <option value="partner">Партнёр</option>
                  <option value="admin">Администратор</option>
                  <option value="superadmin">Суперадмин</option>
                </select>
                {(!isSuperadmin || selected.id === me?.id) && (
                  <span className="text-xs font-normal text-zinc-500">
                    {selected.id === me?.id ? "Свою роль изменить нельзя." : "Менять роль может только суперадмин."}
                  </span>
                )}
              </label>
            </div>

            <div>
              <p className="mb-2 text-sm font-medium">Теги доступа</p>
              {tags.length ? (
                <div className="flex flex-wrap gap-2">{tags.map((tag) => {
                  const on = selectedTags.includes(tag.id);
                  return <button key={tag.id} type="button" aria-pressed={on}
                    onClick={() => setSelectedTags(on ? selectedTags.filter((id) => id !== tag.id) : [...selectedTags, tag.id])}
                    className={`rounded-full border px-3 py-1.5 text-xs ${on ? "border-amber-300 bg-amber-50 text-amber-900" : "border-zinc-200 text-zinc-600 hover:bg-zinc-50"}`}>
                    {tag.name}
                  </button>;
                })}</div>
              ) : <p className="text-xs text-zinc-500">Теги не созданы — доступ к модулям открыт по общим правилам.</p>}
            </div>

            <div className="rounded-xl bg-zinc-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Результаты</p>
              {detailLoading ? <p role="status" className="mt-2 text-sm text-zinc-500">Считаем прогресс…</p> : detail ? (
                <>
                  <div className="mt-2 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                    <div><p className="text-lg font-semibold">{detail.stats?.attempts_total ?? 0}</p><p className="text-xs text-zinc-500">попыток тестов</p></div>
                    <div><p className="text-lg font-semibold">{detail.stats?.attempts_passed ?? 0}</p><p className="text-xs text-zinc-500">успешных</p></div>
                    <div><p className="text-lg font-semibold">{detail.stats?.events_total ?? 0}</p><p className="text-xs text-zinc-500">событий обучения</p></div>
                    <div><p className="text-lg font-semibold">{detail.modules_progress?.overall_progress?.percent ?? 0}%</p><p className="text-xs text-zinc-500">пройдено шагов</p></div>
                  </div>
                  {!!detail.modules_progress?.completed?.length && (
                    <div className="mt-3"><p className="text-xs font-medium text-emerald-800">Завершено модулей: {detail.modules_progress.completed.length}</p>
                      <p className="mt-1 text-xs leading-6 text-zinc-600">{detail.modules_progress.completed.map((m) => m.title).join(", ")}</p></div>
                  )}
                  {!!detail.modules_progress?.in_progress?.length && (
                    <div className="mt-2"><p className="text-xs font-medium text-amber-800">В работе: {detail.modules_progress.in_progress.length}</p>
                      <p className="mt-1 text-xs leading-6 text-zinc-600">{detail.modules_progress.in_progress.map((m) => `${m.title} — ${m.percent}%`).join(", ")}</p></div>
                  )}
                </>
              ) : <p className="mt-2 text-sm text-zinc-500">Нет данных.</p>}
            </div>
          </div>
        )}
      </Modal>

      <Modal open={tagsOpen} title="Теги доступа" onClose={() => { if (!busy) setTagsOpen(false); }} disableClose={busy} className="max-w-lg"
        footer={<div className="flex justify-end"><Button variant="outline" className={btn} disabled={busy} onClick={() => setTagsOpen(false)}>Готово</Button></div>}>
        <div className="space-y-4">
          <p className="text-sm leading-6 text-zinc-600">
            Тег — это группа сотрудников. Модуль можно открыть только тем, у кого есть его тег,
            поэтому теги создаются здесь, а выдаются в карточке сотрудника.
          </p>
          <div className="flex gap-2">
            <input className={field} value={newTagName} placeholder="Например: Менеджеры продаж"
              onChange={(e) => setNewTagName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void createTag(); } }} />
            <Button className={btn} disabled={busy || !newTagName.trim()} onClick={() => void createTag()}>
              {busy ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}Создать
            </Button>
          </div>
          {tags.length ? (
            <ul className="divide-y divide-zinc-100 rounded-xl border border-zinc-200">
              {tags.map((tag) => (
                <li key={tag.id} className="flex items-center justify-between gap-3 px-4 py-3">
                  <span className="text-sm text-zinc-900">{tag.name}</span>
                  <Button variant="ghost" size="sm" className={`${btn} text-rose-600`} disabled={busy}
                    onClick={() => void deleteTag(tag)}>
                    <Trash2 size={14} />Удалить
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="rounded-xl bg-zinc-50 p-4 text-sm text-zinc-600">
              Тегов пока нет. Создайте первый — без тегов доступ к модулям работает по общим правилам.
            </p>
          )}
        </div>
      </Modal>

      <Modal open={creating} title="Новый пользователь" onClose={() => { if (!busy) setCreating(false); }} disableClose={busy} className="max-w-lg"
        footer={<div className="flex justify-end gap-2">
          <Button variant="ghost" className={btn} disabled={busy} onClick={() => setCreating(false)}>Отмена</Button>
          <Button className={btn} disabled={busy || !newUser.name.trim() || !newUser.email.trim()} onClick={() => void createUser()}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}Создать
          </Button>
        </div>}>
        <div className="space-y-4">
          <label className="block space-y-1.5 text-sm font-medium">Имя
            <input autoFocus className={field} value={newUser.name} onChange={(e) => setNewUser({ ...newUser, name: e.target.value })} />
          </label>
          <label className="block space-y-1.5 text-sm font-medium">Почта (логин)
            <input className={field} value={newUser.email} onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} placeholder="name@company.ru" />
          </label>
          <label className="block space-y-1.5 text-sm font-medium">Должность <span className="font-normal text-zinc-400">(необязательно)</span>
            <input className={field} value={newUser.position} onChange={(e) => setNewUser({ ...newUser, position: e.target.value })} />
          </label>
          <p className="flex items-start gap-2 text-xs leading-6 text-zinc-500"><ShieldCheck size={15} className="mt-0.5 shrink-0 text-emerald-700" />
            Пароль генерируется автоматически и показывается один раз. При первом входе система попросит его сменить.</p>
        </div>
      </Modal>

      <Modal open={!!tempPassword} title="Временный пароль" onClose={() => setTempPassword(null)} className="max-w-md"
        footer={<div className="flex justify-end gap-2">
          <Button variant="outline" className={btn} onClick={() => void copyPassword()}>{copied ? <Check size={15} /> : <Copy size={15} />}{copied ? "Скопировано" : "Скопировать"}</Button>
          <Button className={btn} onClick={() => setTempPassword(null)}>Готово</Button>
        </div>}>
        {tempPassword && (
          <div className="space-y-3">
            <p className="text-sm text-zinc-600">Передайте пароль пользователю «{tempPassword.name}». Он больше не будет показан.</p>
            <p className="select-all rounded-xl bg-zinc-900 px-4 py-3 text-center font-mono text-lg text-white">{tempPassword.password}</p>
            <p className="flex items-center gap-2 text-xs text-amber-800"><X size={14} />После первого входа система потребует сменить пароль.</p>
          </div>
        )}
      </Modal>

      {!!filtered.length && (
        <p className="flex items-center gap-2 text-xs text-zinc-500"><UserRound size={14} />Показано {filtered.length} из {items.length}.</p>
      )}
    </div>
  );
}
