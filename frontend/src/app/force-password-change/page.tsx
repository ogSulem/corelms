"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { AppShell } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

export default function ForcePasswordChangePage() {
  const router = useRouter();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [phone, setPhone] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/auth/me", { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as { authenticated: boolean; user?: { must_change_password?: boolean } };
        if (data.authenticated && !data.user?.must_change_password) {
          router.replace("/dashboard");
        }
      } catch {
        // ignore
      }
    })();
  }, [router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      if (String(newPassword || "") !== String(confirmPassword || "")) {
        throw new Error("Пароли не совпадают");
      }
      if (!String(phone || "").trim()) {
        throw new Error("Укажите номер телефона");
      }

      await apiFetch<any>("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
          confirm_password: confirmPassword,
          phone: phone,
        }),
        // UX: password change must be responsive; allow slightly longer than default.
        ...( { timeoutMs: 45_000 } as any ),
      } as any);

      window.dispatchEvent(new Event("corelms:refresh-me"));
      window.dispatchEvent(
        new CustomEvent("corelms:toast", {
          detail: { title: "Пароль обновлён", description: "Теперь можно продолжить обучение." },
        })
      );
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сменить пароль");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AppShell>
      <main className="mx-auto grid min-h-[calc(100vh-72px)] max-w-6xl place-items-center px-6 py-12">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>Смена пароля</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-zinc-600">
              Администратор выдал временный пароль. Перед началом работы нужно задать новый.
            </p>

            <form onSubmit={onSubmit} className="mt-4 grid gap-4">
              <label className="grid gap-1 text-sm">
                <span className="text-zinc-600">Текущий пароль</span>
                <input
                  className="h-10 rounded-xl border border-zinc-200 bg-white px-3 text-zinc-950 outline-none placeholder:text-zinc-400 focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15"
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  required
                />
              </label>

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

              <label className="grid gap-1 text-sm">
                <span className="text-zinc-600">Номер телефона</span>
                <input
                  className="h-10 rounded-xl border border-zinc-200 bg-white px-3 text-zinc-950 outline-none placeholder:text-zinc-400 focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15"
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="+7..."
                  required
                />
              </label>

              {error && (
                <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                  {error}
                </div>
              )}

              <Button disabled={loading} type="submit">
                {loading ? "Сохраняем..." : "Сменить пароль"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </main>
    </AppShell>
  );
}
