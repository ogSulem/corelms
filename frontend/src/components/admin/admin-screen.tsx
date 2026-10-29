"use client";

import type { ReactNode } from "react";

import { AdminNav } from "@/components/admin/admin-nav";
import { ImportAdmin } from "@/components/admin/import-admin";
import { ResultsAdmin } from "@/components/admin/results-admin";
import { UsersAdmin } from "@/components/admin/users-admin";
import { AppShell } from "@/components/app/shell";
import { useAuth } from "@/lib/hooks/use-auth";

/** Общая рамка админ-экранов: одна проверка доступа, один заголовок, одна навигация. */
export function AdminScreen({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  const { user, loading } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";
  return (
    <AppShell>
      <div className="mx-auto w-full max-w-7xl px-4 py-8 sm:py-10">
        {loading ? (
          <p role="status" className="py-10 text-center text-sm text-zinc-500">Проверяем доступ…</p>
        ) : !isAdmin ? (
          <p role="alert" className="py-10 text-center">Раздел доступен только администраторам.</p>
        ) : (
          <>
            <div className="mb-7">
              <p className="text-xs font-semibold uppercase tracking-widest text-amber-800">Админ-центр</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-950">{title}</h1>
              <p className="mt-2 text-sm text-zinc-500">{subtitle}</p>
            </div>
            <AdminNav />
            {children}
          </>
        )}
      </div>
    </AppShell>
  );
}

export function AdminUsersScreen() {
  return (
    <AdminScreen title="Пользователи" subtitle="Люди, их роли, доступ к модулям и результаты обучения.">
      <UsersAdmin />
    </AdminScreen>
  );
}

export function AdminResultsScreen() {
  return (
    <AdminScreen title="Результаты" subtitle="Кто что прошёл: прогресс по модулям и по людям в одном экране.">
      <ResultsAdmin />
    </AdminScreen>
  );
}

export function AdminImportScreen() {
  return (
    <AdminScreen title="Импорт" subtitle="Новый модуль из ZIP-архива и очередь фонового разбора.">
      <ImportAdmin />
    </AdminScreen>
  );
}
