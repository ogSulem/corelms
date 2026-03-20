"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { UserItem, UserDetail, UserHistoryDetailedItem, TagItem } from "../types";
import { useEffect, useMemo, useState } from "react";

interface UsersTabProps {
  currentUserId: string;
  currentUserRole?: string;
  newUserBusy: boolean;
  createUser: () => Promise<void>;
  newUserName: string;
  setNewUserName: (val: string) => void;
  newUserEmail: string;
  setNewUserEmail: (val: string) => void;
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
    email?: string | null;
    position?: string | null;
    role?: "employee" | "admin" | "superadmin" | null;
    must_change_password?: boolean | null;
  }) => Promise<void>;
  resetBusy: boolean;
  resetPassword: () => Promise<void>;
  deleteUserBusy: boolean;
  deleteSelectedUser: () => Promise<void>;
  userHistoryLoading: boolean;
  userHistoryDetailed: UserHistoryDetailedItem[];
  resetTempPassword: string;
  tempPasswordModalOpen: boolean;
  setTempPasswordModalOpen: (open: boolean) => void;

  tags: TagItem[];
  tagsLoading: boolean;
  newTagName: string;
  setNewTagName: (val: string) => void;
  newTagBusy: boolean;
  createTag: () => Promise<void>;
  setSelectedUserTags: (tagIds: string[]) => Promise<void>;

  bulkTagId: string;
  setBulkTagId: React.Dispatch<React.SetStateAction<string>>;
  bulkTagUsers: string[];
  setBulkTagUsers: React.Dispatch<React.SetStateAction<string[]>>;
  bulkTagBusy: boolean;
  loadBulkTagUsers: (tagId: string) => Promise<void>;
  saveBulkTagUsers: (tagId: string, userIds: string[]) => Promise<void>;
}

export function UsersTab(props: UsersTabProps) {
  const {
    currentUserId,
    currentUserRole,
    newUserBusy,
    createUser,
    newUserName,
    setNewUserName,
    newUserEmail,
    setNewUserEmail,
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
    resetBusy,
    resetPassword,
    deleteUserBusy,
    deleteSelectedUser,
    userHistoryLoading,
    userHistoryDetailed,
    resetTempPassword,
    tempPasswordModalOpen,
    setTempPasswordModalOpen,

    tags,
    tagsLoading,
    newTagName,
    setNewTagName,
    newTagBusy,
    createTag,
    setSelectedUserTags,

    bulkTagId,
    setBulkTagId,
    bulkTagUsers,
    setBulkTagUsers,
    bulkTagBusy,
    loadBulkTagUsers,
    saveBulkTagUsers,
  } = props;

  const isSuperadmin = String(currentUserRole || "").trim().toLowerCase() === "superadmin";

  const roleLabel = (role: any): string => {
    const r = String(role || "").trim().toLowerCase();
    if (r === "superadmin") return "СУПЕРАДМИН";
    if (r === "admin") return "АДМИН";
    if (r === "employee") return "ПАРТНЁР";
    if (!r) return "—";
    return String(role || "").toUpperCase();
  };

  const isSelf = Boolean(selectedUserId) && String(selectedUserId) === String(currentUserId || "");
  const targetRole = String(userDetail?.role || "").trim().toLowerCase();
  const isLockedAdminTarget = !isSuperadmin && (targetRole === "admin" || targetRole === "superadmin") && !isSelf;

  const [draftName, setDraftName] = useState<string>("");
  const [draftEmail, setDraftEmail] = useState<string>("");
  const [draftRole, setDraftRole] = useState<"employee" | "admin" | "superadmin">("employee");
  const [historyOpen, setHistoryOpen] = useState(false);

  const [tagDraft, setTagDraft] = useState<string[]>([]);
  const [tagSaving, setTagSaving] = useState(false);

  const [bulkUsersOpen, setBulkUsersOpen] = useState(false);
  const [userTagsOpen, setUserTagsOpen] = useState(false);

  const hasDraft = useMemo(() => {
    if (!userDetail) return false;
    return (
      String(draftName || "") !== String(userDetail.name || "") ||
      String(draftEmail || "") !== String(userDetail.email || "") ||
      String(draftRole || "") !== String(userDetail.role || "")
    );
  }, [draftName, draftEmail, draftRole, userDetail]);

  useEffect(() => {
    if (!userDetail) {
      setDraftName("");
      setDraftEmail("");
      setDraftRole("employee");
      setTagDraft([]);
      return;
    }
    setDraftName(String(userDetail.name || ""));
    setDraftEmail(String(userDetail.email || ""));
    setDraftRole((String((userDetail as any).role || "employee") as any) || "employee");
    setTagDraft(Array.isArray((userDetail as any)?.tag_ids) ? (userDetail as any).tag_ids.map((x: any) => String(x)) : []);
  }, [userDetail?.id]);

  const hasTagDraft = useMemo(() => {
    const cur = Array.isArray((userDetail as any)?.tag_ids) ? (userDetail as any).tag_ids.map((x: any) => String(x)) : [];
    const a = [...cur].sort().join(",");
    const b = [...(tagDraft || [])].map(String).sort().join(",");
    return a !== b;
  }, [userDetail, tagDraft]);

  return (
    <React.Fragment>
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
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewUserName(e.target.value)}
                placeholder="Например: Иван Петров"
              />
            </div>

            <div className="lg:col-span-4">
              <div className="text-[9px] font-black text-zinc-600 uppercase tracking-widest ml-1">Email</div>
              <input
                className="mt-2 w-full h-12 rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
                value={newUserEmail}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewUserEmail(e.target.value)}
                placeholder="name@company.com"
              />
            </div>
            <div className="lg:col-span-2" />
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

        <div className="lg:col-span-4 relative z-50 overflow-visible rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-6 shadow-2xl shadow-zinc-950/10">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Теги</div>
              <div className="mt-2 text-sm font-black uppercase tracking-tight text-zinc-950">Выдача доступа по группам</div>
            </div>
            <Button
              variant="ghost"
              className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
              disabled={bulkTagBusy && !bulkTagId}
              onClick={() => {
                setBulkTagId("");
                setBulkTagUsers([]);
                setBulkUsersOpen(false);
              }}
            >
              ОЧИСТИТЬ
            </Button>
          </div>

          <div className="mt-5 grid gap-5">
            <div>
              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500 ml-1">Создать тег</div>
              <div className="mt-2 flex items-center gap-2">
                <input
                  className="h-11 flex-1 rounded-2xl border border-zinc-200 bg-white px-4 text-[11px] font-black uppercase tracking-widest text-zinc-900 outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
                  value={newTagName}
                  onChange={(e) => setNewTagName(String(e.target.value || ""))}
                  placeholder="НАПР. КАЗАНЬ"
                  disabled={newTagBusy || bulkTagBusy}
                />
                <Button
                  className="h-11 rounded-2xl font-black uppercase tracking-widest text-[9px] whitespace-nowrap"
                  disabled={newTagBusy || bulkTagBusy || !String(newTagName || "").trim()}
                  onClick={() => void createTag()}
                >
                  {newTagBusy ? "СОЗДАНИЕ..." : "СОЗДАТЬ"}
                </Button>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between gap-3">
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500 ml-1">Выбор тега</div>
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">{tagsLoading ? "ЗАГРУЗКА" : `${(tags || []).length}`}</div>
              </div>

              <select
                className="mt-2 w-full h-11 rounded-2xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all appearance-none cursor-pointer"
                value={bulkTagId}
                disabled={tagsLoading || bulkTagBusy}
                onChange={(e: React.ChangeEvent<HTMLSelectElement>) => {
                  const tid = String(e.target.value || "");
                  setBulkTagId(tid);
                  setBulkTagUsers([]);
                  setBulkUsersOpen(false);
                  if (tid) void loadBulkTagUsers(tid);
                }}
              >
                <option value="">ВЫБРАТЬ ТЕГ</option>
                {(tags || []).map((t) => (
                  <option key={String((t as any)?.id || "")} value={String((t as any)?.id || "")}>
                    {String((t as any)?.name || "").toUpperCase()}
                  </option>
                ))}
              </select>

              <div className="mt-3 flex flex-wrap gap-2">
                {(tags || []).slice(0, 14).map((t) => {
                  const tid = String((t as any)?.id || "");
                  const active = Boolean(bulkTagId) && String(bulkTagId) === tid;
                  return (
                    <button
                      key={tid}
                      type="button"
                      className={
                        "h-8 px-3 rounded-full border text-[9px] font-black uppercase tracking-widest transition " +
                        (active
                          ? "border-[#fe9900]/25 bg-[#fe9900]/15 text-zinc-950"
                          : "border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50")
                      }
                      disabled={tagsLoading || bulkTagBusy}
                      onClick={() => {
                        setBulkTagId(tid);
                        setBulkTagUsers([]);
                        setBulkUsersOpen(false);
                        void loadBulkTagUsers(tid);
                      }}
                      title={String((t as any)?.name || "")}
                    >
                      {String((t as any)?.name || "").toUpperCase()}
                    </button>
                  );
                })}
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between gap-4">
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500 ml-1">Партнёры в теге</div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
                    disabled={!bulkTagId || bulkTagBusy || usersLoading}
                    onClick={() => void saveBulkTagUsers(bulkTagId, bulkTagUsers)}
                  >
                    {bulkTagBusy ? "СОХРАНЕНИЕ..." : "ПРИМЕНИТЬ"}
                  </Button>
                </div>
              </div>

              {!bulkTagId ? (
                <div className="mt-2 text-[10px] font-bold text-zinc-400 uppercase tracking-widest ml-1">Выберите тег</div>
              ) : usersLoading ? (
                <div className="mt-2 text-[10px] font-bold text-zinc-400 uppercase tracking-widest ml-1">Загрузка…</div>
              ) : (
                <div className="mt-2 relative">
                  <button
                    type="button"
                    className="w-full h-11 rounded-2xl border border-zinc-200 bg-white px-4 text-left text-[10px] font-black uppercase tracking-widest text-zinc-900 hover:bg-zinc-50 outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
                    onClick={() => setBulkUsersOpen((v) => !v)}
                    disabled={bulkTagBusy}
                  >
                    <span className="inline-flex items-center justify-between w-full">
                      <span>{bulkTagUsers?.length ? `ВЫБРАНО: ${bulkTagUsers.length}` : "ВЫБРАТЬ ПАРТНЁРОВ"}</span>
                      <span className="text-zinc-400">▾</span>
                    </span>
                  </button>

                  {bulkUsersOpen ? (
                    <div className="absolute z-[9999] mt-2 w-full rounded-[24px] border border-zinc-200 bg-white shadow-2xl shadow-zinc-950/10 overflow-hidden">
                      <div className="p-2">
                        <div className="max-h-[280px] overflow-auto pr-1 space-y-2">
                          {(users || []).map((u) => {
                            const uid = String((u as any)?.id || "");
                            const checked = (bulkTagUsers || []).includes(uid);
                            return (
                              <label
                                key={uid}
                                className={
                                  "flex items-center gap-3 rounded-2xl border px-3 py-2.5 transition " +
                                  (checked ? "border-[#fe9900]/25 bg-[#fe9900]/10" : "border-zinc-200 bg-white hover:bg-zinc-50")
                                }
                              >
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  disabled={bulkTagBusy}
                                  onChange={() => {
                                    setBulkTagUsers((prev: string[]) => {
                                      const xs = Array.isArray(prev) ? prev.slice() : [];
                                      const has = xs.includes(uid);
                                      return has ? xs.filter((x) => x !== uid) : [...xs, uid];
                                    });
                                  }}
                                />
                                <div className="min-w-0 flex-1">
                                  <div className="text-[10px] font-black uppercase tracking-widest text-zinc-900 truncate">
                                    {String((u as any)?.name || "")}
                                  </div>
                                  {String((u as any)?.email || "").trim() ? (
                                    <div className="mt-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-500 truncate">
                                      {String((u as any)?.email || "")}
                                    </div>
                                  ) : null}
                                </div>
                              </label>
                            );
                          })}
                        </div>

                        <div className="mt-2 flex items-center justify-between gap-2">
                          <button
                            type="button"
                            className="h-10 px-4 rounded-2xl border border-zinc-200 bg-white text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                            onClick={() => {
                              setBulkTagUsers([]);
                            }}
                          >
                            СБРОСИТЬ
                          </button>
                          <button
                            type="button"
                            className="h-10 px-4 rounded-2xl border border-zinc-200 bg-white text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                            onClick={() => setBulkUsersOpen(false)}
                          >
                            ГОТОВО
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-12 items-start">
        <div className="lg:col-span-5 relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-6 shadow-2xl shadow-zinc-950/10">
          <div className="flex items-center justify-between gap-4">
            <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Партнёры</div>
            <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600">{users.length}</div>
          </div>

          <div className="mt-4">
            <input
              className="w-full h-11 rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
              value={userQuery}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setUserQuery(e.target.value)}
              placeholder="ПОИСК ПО ИМЕНИ"
            />
          </div>

          <div className="mt-4 space-y-2 max-h-[640px] overflow-auto pr-1">
            {(users || [])
              .filter((u) => {
                const q = (userQuery || "").trim().toLowerCase();
                if (!q) return true;
                return String(u.name || "").toLowerCase().includes(q);
              })
              .map((u) => {
                const active = String(u.id) === String(selectedUserId);
                const roleText = roleLabel((u as any)?.role);
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
                        {String((u as any)?.email || "").trim() ? (
                          <div className="mt-1 truncate text-[10px] font-black uppercase tracking-widest text-zinc-500">
                            {String((u as any)?.email || "").trim()}
                          </div>
                        ) : null}
                        <div className="mt-1 truncate text-[10px] font-black uppercase tracking-widest text-zinc-600">
                          {roleText}
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
                      <div className="shrink-0 text-[9px] font-black uppercase tracking-widest text-zinc-500">{roleText}</div>
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
                  {userDetail ? userDetail.name : selectedUserId ? "Загрузка..." : "Выберите партнёра"}
                </div>
              </div>

              <div className="shrink-0 flex flex-col gap-2">
                <Button
                  variant="ghost"
                  className="h-11 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  disabled={!selectedUserId || userDetailLoading || !userDetail || !hasDraft || isLockedAdminTarget}
                  onClick={() =>
                    void updateSelectedUser({
                      name: String(draftName || "").trim() || null,
                      email: String(draftEmail || "").trim() || null,
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
                  disabled={!selectedUserId || resetBusy || isLockedAdminTarget}
                  onClick={resetPassword}
                >
                  {resetBusy ? "СБРОС..." : "СБРОСИТЬ ПАРОЛЬ"}
                </Button>
                <Button
                  variant="destructive"
                  className="h-11 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  disabled={!selectedUserId || deleteUserBusy || isSelf || isLockedAdminTarget}
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
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => setDraftName(String(e.target.value || ""))}
                      disabled={isLockedAdminTarget}
                    />
                  </div>
                  <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Email</div>
                    <input
                      className="mt-2 w-full h-11 rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all"
                      value={draftEmail}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => setDraftEmail(String(e.target.value || ""))}
                      placeholder="name@company.com"
                      disabled={isLockedAdminTarget}
                    />
                  </div>
                  <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Роль</div>
                    <select
                      className="mt-2 w-full h-11 rounded-xl bg-white border border-zinc-200 px-4 text-[11px] font-black text-zinc-950 uppercase tracking-widest outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all appearance-none cursor-pointer"
                      value={draftRole}
                      onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setDraftRole((String(e.target.value || "employee") as any) || "employee")}
                      disabled={!isSuperadmin || isLockedAdminTarget}
                    >
                      <option value="employee">ПАРТНЁР</option>
                      <option value="admin">АДМИН</option>
                      <option value="superadmin">СУПЕРАДМИН</option>
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
                    <div>
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Теги</div>
                      <div className="mt-1 text-[10px] font-bold text-zinc-600 uppercase tracking-widest">Доступ к модулям (OR)</div>
                    </div>
                    <Button
                      variant="ghost"
                      className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
                      disabled={!selectedUserId || tagSaving || tagsLoading || isLockedAdminTarget || !hasTagDraft}
                      onClick={async () => {
                        try {
                          setTagSaving(true);
                          await setSelectedUserTags(tagDraft);
                        } finally {
                          setTagSaving(false);
                        }
                      }}
                    >
                      {tagSaving ? "СОХРАН..." : "СОХРАНИТЬ ТЕГИ"}
                    </Button>
                  </div>

                  <div className="mt-4">
                    <div className="rounded-2xl border border-zinc-200 bg-zinc-50 p-4">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Выбор тегов</div>
                      {tagsLoading ? (
                        <div className="mt-2 text-[10px] font-bold text-zinc-400 uppercase tracking-widest">Загрузка…</div>
                      ) : (tags || []).length === 0 ? (
                        <div className="mt-2 text-[10px] font-bold text-zinc-400 uppercase tracking-widest">Нет тегов</div>
                      ) : (
                        <div className="mt-2 relative">
                          <button
                            type="button"
                            className="w-full h-10 rounded-xl border border-zinc-200 bg-white px-3 text-left text-[10px] font-black uppercase tracking-widest text-zinc-800 hover:bg-zinc-50"
                            onClick={() => setUserTagsOpen((v) => !v)}
                            disabled={tagSaving || isLockedAdminTarget}
                          >
                            {tagDraft?.length ? `ВЫБРАНО: ${tagDraft.length}` : "ВЫБРАТЬ ТЕГИ"}
                          </button>

                          {userTagsOpen ? (
                            <div className="absolute z-30 mt-2 w-full rounded-2xl border border-zinc-200 bg-white shadow-2xl p-3">
                              <div className="max-h-[320px] overflow-auto pr-2 space-y-1">
                                {(tags || []).map((t) => {
                                  const id = String((t as any)?.id || "");
                                  const checked = (tagDraft || []).includes(id);
                                  return (
                                    <label key={id} className="flex items-center gap-3 rounded-xl border border-zinc-200 bg-white px-4 py-3 hover:bg-zinc-50 cursor-pointer transition-colors">
                                      <input
                                        type="checkbox"
                                        className="w-4 h-4 text-[#fe9900] border-zinc-300 rounded focus:ring-[#fe9900]/20"
                                        checked={checked}
                                        disabled={tagSaving || isLockedAdminTarget}
                                        onChange={() => {
                                          setTagDraft((prev) => {
                                            const xs = Array.isArray(prev) ? prev.slice() : [];
                                            const has = xs.includes(id);
                                            return has ? xs.filter((x) => x !== id) : [...xs, id];
                                          });
                                        }}
                                      />
                                      <div className="text-[11px] font-black uppercase tracking-widest text-zinc-800 truncate">{String((t as any)?.name || "")}</div>
                                    </label>
                                  );
                                })}
                              </div>
                              <div className="mt-2 flex items-center justify-between gap-2">
                                <button
                                  type="button"
                                  className="h-9 px-3 rounded-xl border border-zinc-200 bg-white text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                                  onClick={() => { setTagDraft([]); }}
                                  disabled={tagSaving || isLockedAdminTarget}
                                >
                                  СБРОСИТЬ
                                </button>
                                <button
                                  type="button"
                                  className="h-9 px-3 rounded-xl border border-zinc-200 bg-white text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                                  onClick={() => setUserTagsOpen(false)}
                                >
                                  ГОТОВО
                                </button>
                              </div>
                            </div>
                          ) : null}
                        </div>
                      )}
                    </div>
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
                </div>

                <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                  <div className="flex items-end justify-between gap-4">
                    <div>
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Общий прогресс</div>
                      <div className="mt-2 text-[11px] font-black uppercase tracking-widest text-zinc-900">
                        {Number((userDetail as any)?.modules_progress?.overall_progress?.steps_completed || 0)} / {Number((userDetail as any)?.modules_progress?.overall_progress?.steps_total || 0)} шагов
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">%</div>
                      <div className="mt-1 text-2xl font-black tabular-nums text-zinc-950">
                        {Math.max(0, Math.min(100, Number((userDetail as any)?.modules_progress?.overall_progress?.percent || 0)))}%
                      </div>
                    </div>
                  </div>
                  <div className="mt-4 h-2 w-full rounded-full bg-zinc-100 overflow-hidden border border-zinc-200">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-[#fe9900] to-[#284e13] transition-all duration-700"
                      style={{ width: `${Math.max(0, Math.min(100, Number((userDetail as any)?.modules_progress?.overall_progress?.percent || 0)))}%` }}
                    />
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
                              <div className="text-[10px] font-black text-[#fe9900] tabular-nums shrink-0">{m.percent}%</div>
                            </div>
                            <div className="h-1.5 w-full rounded-full bg-zinc-100 overflow-hidden">
                              <div className="h-full bg-[#fe9900] transition-all duration-500" style={{ width: `${m.percent}%` }} />
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
                        onClick={() => setHistoryOpen(true)}
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

                  <Modal
                    open={tempPasswordModalOpen}
                    onClose={() => setTempPasswordModalOpen(false)}
                    title="Доступ пользователю"
                    className="max-w-[min(92vw,560px)]"
                  >
                    <div className="space-y-4">
                      <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Инструкция</div>
                        <div className="mt-2 text-[11px] font-bold text-zinc-800">
                          1) Передай пользователю временный пароль ниже.
                          <br />
                          2) Пользователь входит в систему.
                          <br />
                          3) При первом входе система потребует сменить пароль.
                        </div>
                      </div>

                      <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                        <div className="flex items-center justify-between gap-4">
                          <div className="text-[9px] font-black uppercase tracking-widest text-[#fe9900]">Временный пароль</div>
                          <button
                            className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                            onClick={() => void copy(String(resetTempPassword || newUserTempPassword || ""))}
                            type="button"
                          >
                            КОПИРОВАТЬ
                          </button>
                        </div>
                        <div className="mt-2 text-sm font-black text-zinc-950 break-all">
                          {String(resetTempPassword || newUserTempPassword || "").trim() || "—"}
                        </div>
                      </div>
                    </div>
                  </Modal>
                </div>
            ) : (
              <div className="mt-8 py-12 text-center text-[10px] font-black uppercase tracking-widest text-zinc-600">
                {selectedUserId ? "НЕТ ДАННЫХ" : "ВЫБЕРИТЕ ПАРТНЁРА"}
              </div>
            )}
          </div>
        </div>
      </div>

      <Modal
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        title="История пользователя"
        className="max-w-[min(92vw,860px)]"
      >
        <div className="space-y-4">
          {userHistoryLoading ? (
            <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest">Загрузка…</div>
          ) : !userHistoryDetailed || userHistoryDetailed.length === 0 ? (
            <div className="py-10 text-center text-[10px] font-black uppercase tracking-widest text-zinc-600 border border-dashed border-zinc-200 rounded-[28px]">
              История пуста
            </div>
          ) : (
            <div className="max-h-[70vh] overflow-auto pr-1 space-y-2">
              {(userHistoryDetailed || []).map((h) => (
                <div key={h.id} className="rounded-2xl border border-zinc-100 bg-zinc-50/50 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="text-[11px] font-black text-zinc-950 uppercase tracking-tight truncate">{h.title}</div>
                      {h.subtitle ? (
                        <div className="mt-1 text-[10px] font-bold text-zinc-500 uppercase tracking-tight truncate">{h.subtitle}</div>
                      ) : null}
                    </div>
                    <div className="text-[10px] text-zinc-500 tabular-nums shrink-0">
                      {new Date(h.created_at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="flex justify-end">
            <Button variant="outline" className="rounded-2xl" onClick={() => setHistoryOpen(false)}>
              Закрыть
            </Button>
          </div>
        </div>
      </Modal>
      </div>
    </React.Fragment>
  );
}
