"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { AppShell } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

function ResetPasswordInner() {
  const router = useRouter();
  const sp = useSearchParams();

  const token = useMemo(() => String(sp.get("token") || "").trim(), [sp]);

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [ok, setOk] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    setOk(false);
  }, [token]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) {
      setError("Ссылка недействительна: отсутствует токен");
      return;
    }
    if (String(newPassword || "") !== String(confirmPassword || "")) {
      setError("Пароли не совпадают");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      await apiFetch<any>("/auth/reset-password/confirm", {
        method: "POST",
        body: JSON.stringify({
          token,
          new_password: newPassword,
          confirm_password: confirmPassword,
        }),
        ...({ timeoutMs: 45_000 } as any),
      } as any);

      setOk(true);
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: { title: "Пароль установлен", description: "Теперь вы можете войти в систему." },
        })
      );
      router.replace("/login");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось установить пароль");
      setOk(false);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto grid min-h-[calc(100vh-72px)] max-w-6xl place-items-center px-6 py-12">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Установка пароля</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-zinc-600">Перейдите по ссылке от администратора и задайте новый пароль.</p>

          <form onSubmit={onSubmit} className="mt-4 grid gap-4">
            <label className="grid gap-1 text-sm">
              <span className="text-zinc-600">Новый пароль</span>
              <input
                className="h-10 rounded-xl border border-zinc-200 bg-white px-3 text-zinc-950 outline-none placeholder:text-zinc-400 focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
              />
            </label>

            <label className="grid gap-1 text-sm">
              <span className="text-zinc-600">Подтверждение пароля</span>
              <input
                className="h-10 rounded-xl border border-zinc-200 bg-white px-3 text-zinc-950 outline-none placeholder:text-zinc-400 focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
            </label>

            {error && (
              <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                {error}
              </div>
            )}

            <Button disabled={loading} type="submit">
              {loading ? "Сохраняем..." : ok ? "Готово" : "Установить пароль"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}

export default function ResetPasswordPage() {
  return (
    <AppShell>
      <Suspense fallback={null}>
        <ResetPasswordInner />
      </Suspense>
    </AppShell>
  );
}
