"use client";

import { Button } from "@/components/ui/button";
import { UserItem, UserDetail, UserHistoryDetailedItem } from "../adminpanel-client";
import { useEffect, useMemo, useState } from "react";

interface UsersTabProps {
  currentUserId: string;
  newUserBusy: boolean;
  createUser: () => Promise<void>;
  newUserName: string;
  setNewUserName: (val: string) => void;
  newUserPosition: string;
  setNewUserPosition: (val: string) => void;
  newUserRole: "employee" | "admin";
  setNewUserRole: (val: "employee" | "admin") => void;
  usersLoading: boolean;
  loadUsers: () => Promise<void>;
  newUserTempPassword: string;
  copy: (text: string) => void;
  users: UserItem[];
  userQuery: string;
  setUserQuery: (val: string) => void;
  selectedUserId: string;
  setSelectedUserId: (id: string) => void;
  userDetail: UserDetail | null;
  userDetailLoading: boolean;
  updateSelectedUser: (patch: {
    name?: string | null;
    position?: string | null;
    role?: "employee" | "admin" | null;
    must_change_password?: boolean | null;
  }) => Promise<void>;
  forceSelectedUserPasswordChange: () => Promise<void>;
  resetBusy: boolean;
  resetPassword: () => Promise<void>;
  deleteUserBusy: boolean;
  deleteSelectedUser: () => Promise<void>;
  userHistoryLoading: boolean;
  userHistoryDetailed: UserHistoryDetailedItem[];
  setHistoryModalOpen: (open: boolean) => void;
  resetTempPassword: string;
}

export function UsersTab(props: UsersTabProps) {
  const {
    currentUserId,
    newUserBusy,
    createUser,
    newUserName,
    setNewUserName,
    newUserPosition,
    setNewUserPosition,
    newUserRole,
    setNewUserRole,
    usersLoading,
    loadUsers,
    newUserTempPassword,
    copy,
    users,
    userQuery,
    setUserQuery,
    selectedUserId,
    setSelectedUserId,
    userDetail,
    userDetailLoading,
    updateSelectedUser,
    forceSelectedUserPasswordChange,
    resetBusy,
    resetPassword,
    deleteUserBusy,
    deleteSelectedUser,
    userHistoryLoading,
    userHistoryDetailed,
    setHistoryModalOpen,
    resetTempPassword,
  } = props;

  const isSelf = Boolean(selectedUserId) && String(selectedUserId) === String(currentUserId || "");

  const [draftName, setDraftName] = useState<string>("");
  const [draftPosition, setDraftPosition] = useState<string>("");
  const [draftRole, setDraftRole] = useState<"employee" | "admin">("employee");

  const hasDraft = useMemo(() => {
    if (!userDetail) return false;
    return (
      String(draftName || "") !== String(userDetail.name || "") ||
      String(draftPosition || "") !== String(userDetail.position || "") ||
      String(draftRole || "") !== String(userDetail.role || "")
    );
  }, [draftName, draftPosition, draftRole, userDetail]);

  useEffect(() => {
    if (!userDetail) {
      setDraftName("");
      setDraftPosition("");
      setDraftRole("employee");
      return;
    }
    setDraftName(String(userDetail.name || ""));
    setDraftPosition(String(userDetail.position || ""));
    setDraftRole((String(userDetail.role || "employee") as any) === "admin" ? "admin" : "employee");
  }, [userDetail?.id]);

  return (
    <div className="mt-8 space-y-6">
      <div className="grid gap-6 lg:grid-cols-12 items-start">
        <div className="lg:col-span-8 relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-6 shadow-2xl shadow-zinc-950/10">
          <div className="flex items-end justify-between gap-6">
            <div>
              <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900]">Пользователи</div>
              <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">Быстрая выдача доступа</div>
            </div>
            <Button
              className="h-12 rounded-2xl font-black uppercase tracking-widest text-[9px]"
              disabled={newUserBusy}
              onClick={createUser}
            >
              {newUserBusy ? "СОЗДАНИЕ..." : "СОЗДАТЬ"}
            </Button>
          </div>

          <div className="mt-6 grid gap-4 lg:grid-cols-12 items-end">
            <div className="lg:col-span-4">
              <div className="text-[9px] font-black text-zinc-600 uppercase tracking-widest ml-1">Имя</div>
              <input
                className="mt-2 w-full h-12 rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
                value={newUserName}
                onChange={(e) => setNewUserName(e.target.value)}
                placeholder="Например: Иван Петров"
              />
            </div>
            <div className="lg:col-span-4">
              <div className="text-[9px] font-black text-zinc-600 uppercase tracking-widest ml-1">Должность</div>
              <input
                className="mt-2 w-full h-12 rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
                value={newUserPosition}
                onChange={(e) => setNewUserPosition(e.target.value)}
                placeholder="Например: Менеджер"
              />
            </div>
            <div className="lg:col-span-2">
              <div className="text-[9px] font-black text-zinc-600 uppercase tracking-widest ml-1">Роль</div>
              <select
                className="mt-2 w-full h-12 rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all appearance-none cursor-pointer"
                value={newUserRole}
                onChange={(e) => setNewUserRole(e.target.value as any)}
              >
                <option value="employee">СОТРУДНИК</option>
                <option value="admin">АДМИН</option>
              </select>
            </div>
            <div className="lg:col-span-2 flex items-center justify-end">
              <Button
                variant="ghost"
                className="h-12 w-full rounded-xl font-black uppercase tracking-widest text-[9px]"
                disabled={usersLoading}
                onClick={() => void loadUsers()}
              >
                {usersLoading ? "ОБНОВЛЕНИЕ..." : "ОБНОВИТЬ"}
              </Button>
            </div>
          </div>

          {newUserTempPassword ? (
            <div className="mt-4 rounded-2xl border border-zinc-200 bg-white p-4">
              <div className="flex items-center justify-between gap-4">
                <div className="text-[9px] font-black uppercase tracking-widest text-[#fe9900]">Временный пароль</div>
                <button
                  className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                  onClick={() => void copy(newUserTempPassword)}
                  type="button"
                >
                  КОПИРОВАТЬ
                </button>
              </div>
              <div className="mt-2 text-sm font-black text-zinc-950 break-all">{newUserTempPassword}</div>
            </div>
          ) : null}
        </div>

        <div className="lg:col-span-4 relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-6 shadow-2xl shadow-zinc-950/10">
          <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Подсказка</div>
          <div className="mt-2 text-sm font-bold text-zinc-600">
            Админ видит всё. Сотруднику доступен только контент. После входа пользователь должен сменить временный пароль.
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-12 items-start">
        <div className="lg:col-span-5 relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-6 shadow-2xl shadow-zinc-950/10">
          <div className="flex items-center justify-between gap-4">
            <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Сотрудники</div>
            <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600">{users.length}</div>
          </div>

          <div className="mt-4">
            <input
              className="w-full h-11 rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
              value={userQuery}
              onChange={(e) => setUserQuery(e.target.value)}
              placeholder="ПОИСК ПО ИМЕНИ"
            />
          </div>

          <div className="mt-4 space-y-2 max-h-[520px] overflow-auto pr-1">
            {(users || [])
              .filter((u) => {
                const q = (userQuery || "").trim().toLowerCase();
                if (!q) return true;
                return String(u.name || "").toLowerCase().includes(q);
              })
              .map((u) => {
                const active = String(u.id) === String(selectedUserId);
                return (
                  <button
                    key={u.id}
                    type="button"
                    onClick={() => setSelectedUserId(String(u.id))}
                    className={
                      "w-full text-left rounded-2xl border px-4 py-3 transition " +
                      (active ? "border-[#fe9900]/25 bg-[#fe9900]/10" : "border-zinc-200 bg-white hover:bg-zinc-50")
                    }
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-[11px] font-black uppercase tracking-widest text-zinc-950">{u.name}</div>
                        <div className="mt-1 truncate text-[10px] font-black uppercase tracking-widest text-zinc-600">
                          {u.position ? u.position : u.role}
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                            ГОТОВО {Number(u.progress_summary?.completed_count || 0)}
                          </div>
                          <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                            В РАБОТЕ {Number(u.progress_summary?.in_progress_count || 0)}
                          </div>
                          {u.progress_summary?.current ? (
                            <div className="min-w-0 rounded-full border border-[#fe9900]/25 bg-[#fe9900]/10 px-2.5 py-1 text-[9px] font-black uppercase tracking-widest text-zinc-900">
                              <span className="truncate">{String(u.progress_summary.current.title || "").toUpperCase()}</span>
                              <span className="ml-2 tabular-nums">{Number(u.progress_summary.current.percent || 0)}%</span>
                            </div>
                          ) : null}
                        </div>
                      </div>
                      <div className="shrink-0 text-[9px] font-black uppercase tracking-widest text-zinc-500">{u.role}</div>
                    </div>
                  </button>
                );
              })}
          </div>
        </div>

        <div className="lg:col-span-7 space-y-6">
          <div className="relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-10 shadow-2xl shadow-zinc-950/10">
            <div className="flex items-start justify-between gap-6">
              <div>
                <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900] mb-2">Карточка</div>
                <div className="text-2xl font-black tracking-tighter text-zinc-950 uppercase leading-none">
                  {userDetail ? userDetail.name : selectedUserId ? "Загрузка..." : "Выберите сотрудника"}
                </div>
                {userDetail?.position ? (
                  <div className="mt-3 text-sm text-zinc-500 font-bold uppercase tracking-widest">{userDetail.position}</div>
                ) : null}
              </div>

              <div className="shrink-0 flex flex-col gap-2">
                <Button
                  variant="ghost"
                  className="h-11 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  disabled={!selectedUserId || userDetailLoading || !userDetail || !hasDraft}
                  onClick={() =>
                    void updateSelectedUser({
                      name: String(draftName || "").trim() || null,
                      position: String(draftPosition || "").trim() || null,
                      role: (draftRole as any) ?? null,
                      must_change_password: userDetail?.must_change_password ?? null,
                    })
                  }
                >
                  СОХРАНИТЬ
                </Button>
                <Button
                  variant="ghost"
                  className="h-11 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  disabled={!selectedUserId || resetBusy}
                  onClick={resetPassword}
                >
                  {resetBusy ? "СБРОС..." : "СБРОСИТЬ ПАРОЛЬ"}
                </Button>
                <Button
                  variant="ghost"
                  className="h-11 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  disabled={!selectedUserId || userDetailLoading}
                  onClick={forceSelectedUserPasswordChange}
                >
                  СМЕНА ПАРОЛЯ
                </Button>
                <Button
                  variant="destructive"
                  className="h-11 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  disabled={!selectedUserId || deleteUserBusy || isSelf}
                  onClick={deleteSelectedUser}
                >
                  {deleteUserBusy ? "УДАЛЕНИЕ..." : "УДАЛИТЬ"}
                </Button>
              </div>
            </div>

            {userDetailLoading ? (
              <div className="mt-8 flex items-center justify-center py-10">
                <div className="h-12 w-12 rounded-full border-2 border-[#fe9900]/30 border-t-[#fe9900] animate-spin" />
              </div>
            ) : userDetail ? (
              <div className="mt-8 grid gap-4">
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Имя</div>
                    <input
                      className="mt-2 w-full h-11 rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
                      value={draftName}
                      onChange={(e) => setDraftName(String(e.target.value || ""))}
                    />
                  </div>
                  <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Должность</div>
                    <input
                      className="mt-2 w-full h-11 rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
                      value={draftPosition}
                      onChange={(e) => setDraftPosition(String(e.target.value || ""))}
                    />
                  </div>
                  <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Роль</div>
                    <select
                      className="mt-2 w-full h-11 rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all appearance-none cursor-pointer"
                      value={draftRole}
                      onChange={(e) => setDraftRole((e.target.value as any) === "admin" ? "admin" : "employee")}
                      disabled={isSelf}
                    >
                      <option value="employee">СОТРУДНИК</option>
                      <option value="admin">АДМИН</option>
                    </select>
                  </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">XP</div>
                    <div className="mt-2 text-2xl font-black tabular-nums text-zinc-950">{String(userDetail.xp ?? 0)}</div>
                  </div>
                  <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">УРОВЕНЬ</div>
                    <div className="mt-2 text-2xl font-black tabular-nums text-zinc-950">{String(userDetail.level ?? 0)}</div>
                  </div>
                  <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">СЕРИЯ</div>
                    <div className="mt-2 text-2xl font-black tabular-nums text-zinc-950">{String(userDetail.streak ?? 0)}</div>
                  </div>
                </div>

                <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                  <div className="flex flex-wrap items-center justify-between gap-4">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Статус</div>
                    <div
                      className={
                        "rounded-full px-3 py-1 text-[9px] font-black uppercase tracking-widest border " +
                        (userDetail.must_change_password
                          ? "border-rose-500/20 bg-rose-500/10 text-rose-700"
                          : "border-[#284e13]/20 bg-[#284e13]/10 text-[#284e13]")
                      }
                    >
                      {userDetail.must_change_password ? "ТРЕБУЕТ СМЕНЫ ПАРОЛЯ" : "ПАРОЛЬ АКТУАЛЕН"}
                    </div>
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-5">
                    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Назнач.</div>
                      <div className="mt-2 text-lg font-black tabular-nums text-zinc-950">{String(userDetail.stats.assignments_total)}</div>
                    </div>
                    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Выполн.</div>
                      <div className="mt-2 text-lg font-black tabular-nums text-zinc-950">{String(userDetail.stats.assignments_completed)}</div>
                    </div>
                    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Попыток</div>
                      <div className="mt-2 text-lg font-black tabular-nums text-zinc-950">{String(userDetail.stats.attempts_total)}</div>
                    </div>
                    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Сдал</div>
                      <div className="mt-2 text-lg font-black tabular-nums text-zinc-950">{String(userDetail.stats.attempts_passed)}</div>
                    </div>
                    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Событий</div>
                      <div className="mt-2 text-lg font-black tabular-nums text-zinc-950">{String(userDetail.stats.events_total)}</div>
                    </div>
                  </div>

                  <div className="mt-6 grid gap-6 sm:grid-cols-2">
                    <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500 mb-4">В процессе</div>
                      {userDetail.modules_progress.in_progress.length > 0 ? (
                        <div className="space-y-3">
                          {userDetail.modules_progress.in_progress.map((m: { module_id: string; title: string; percent: number }) => (
                            <div key={m.module_id} className="space-y-2">
                              <div className="flex items-center justify-between gap-4">
                                <div className="text-[11px] font-black text-zinc-950 truncate">{m.title}</div>
                                <div className="text-[10px] font-black text-[#fe9900] tabular-nums">{m.percent}%</div>
                              </div>
                              <div className="h-1.5 w-full rounded-full bg-zinc-100 overflow-hidden">
                                <div 
                                  className="h-full bg-[#fe9900] transition-all duration-500" 
                                  style={{ width: `${m.percent}%` }}
                                />
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest">Нет активных модулей</div>
                      )}
                    </div>

                    <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500 mb-4">Завершено</div>
                      {userDetail.modules_progress.completed.length > 0 ? (
                        <div className="space-y-2">
                          {userDetail.modules_progress.completed.map((m: { module_id: string; title: string }) => (
                            <div key={m.module_id} className="flex items-center justify-between gap-4 rounded-xl bg-zinc-50 p-2 border border-zinc-100">
                              <div className="text-[11px] font-black text-zinc-950 truncate">{m.title}</div>
                              <div className="flex h-5 w-5 items-center justify-center rounded-full bg-[#284e13] text-[8px] text-white">✓</div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest">Нет завершенных модулей</div>
                      )}
                    </div>
                  </div>

                  <div className="mt-6 rounded-2xl border border-zinc-200 bg-white p-5">
                    <div className="flex items-center justify-between mb-4">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Последняя активность</div>
                      <button 
                        onClick={() => setHistoryModalOpen(true)}
                        className="text-[9px] font-black uppercase tracking-widest text-[#fe9900] hover:underline"
                      >
                        ВСЯ ИСТОРИЯ
                      </button>
                    </div>
                    <div className="space-y-2">
                      {userHistoryLoading ? (
                        <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest">Загрузка…</div>
                      ) : (
                        (userHistoryDetailed || []).slice(0, 5).map((h) => (
                          <div key={h.id} className="flex items-center justify-between gap-4 text-[11px]">
                            <div className="min-w-0 flex-1">
                              <div className="font-bold text-zinc-900 uppercase tracking-tight truncate">{h.title}</div>
                              {h.subtitle ? (
                                <div className="mt-0.5 text-[10px] font-bold text-zinc-500 uppercase tracking-tight truncate">{h.subtitle}</div>
                              ) : null}
                            </div>
                            <div className="text-[10px] text-zinc-500 tabular-nums shrink-0">
                              {new Date(h.created_at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
                            </div>
                          </div>
                        ))
                      )}
                      {!userHistoryLoading && (!userHistoryDetailed || userHistoryDetailed.length === 0) && (
                        <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest">История пуста</div>
                      )}
                    </div>
                  </div>

                  {resetTempPassword ? (
                    <div className="mt-5 rounded-2xl border border-zinc-200 bg-white p-4">
                      <div className="flex items-center justify-between gap-4">
                        <div className="text-[9px] font-black uppercase tracking-widest text-[#fe9900]">Временный пароль</div>
                        <button
                          className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                          onClick={() => void copy(resetTempPassword)}
                          type="button"
                        >
                          КОПИРОВАТЬ
                        </button>
                      </div>
                      <div className="mt-2 text-sm font-black text-zinc-950 break-all">{resetTempPassword}</div>
                    </div>
                  ) : null}
                </div>
              </div>
            ) : (
              <div className="mt-8 py-12 text-center text-[10px] font-black uppercase tracking-widest text-zinc-600">
                {selectedUserId ? "НЕТ ДАННЫХ" : "ВЫБЕРИТЕ СОТРУДНИКА"}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
