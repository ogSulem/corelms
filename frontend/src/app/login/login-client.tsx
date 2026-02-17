"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff } from "lucide-react";

import { Button } from "@/components/ui/button";

export function LoginClient() {
  const router = useRouter();

  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const loginRef = useRef<HTMLInputElement | null>(null);
  const canSubmit = useMemo(() => {
    return Boolean(String(name || "").trim() && String(password || "").trim() && !loading);
  }, [loading, name, password]);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/auth/me", { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as { authenticated: boolean };
        if (data.authenticated) router.replace("/dashboard");
      } catch {
        // ignore
      }
    })();
  }, [router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const n = String(name || "").trim();
      const p = String(password || "");
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: n, password: p }),
        credentials: "include",
      });
      if (!res.ok) {
        let code = "";
        let message = "";
        try {
          const j = (await res.json()) as any;
          code = String(j?.error_code || "");
          message = String(j?.error_message || "");
        } catch {
          // ignore
        }
        const hint = code ? `${code}` : "";
        throw new Error(message || hint || "Не удалось войти");
      }

      window.dispatchEvent(new Event("corelms:refresh-me"));
      router.refresh();

      router.push("/dashboard");
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if ((msg || "").toLowerCase().includes("invalid_credentials") || (msg || "").toLowerCase().includes("invalid")) {
        setError("НЕВЕРНЫЕ ДАННЫЕ ВХОДА");
      } else if ((msg || "").toLowerCase().includes("upstream_unavailable") || (msg || "").toLowerCase().includes("unavailable") || (msg || "").includes("502")) {
        setError("СЕРВИС ВРЕМЕННО НЕДОСТУПЕН. ПОВТОРИТЕ ПОПЫТКУ.");
      } else {
        setError("ОШИБКА АВТОРИЗАЦИИ. ПОВТОРИТЕ ПОПЫТКУ.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center px-6 py-12">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[-15%] left-[-10%] w-[60%] h-[60%] rounded-full bg-[#fe9900]/10 blur-[120px]" />
        <div className="absolute -bottom-[20%] -right-[10%] w-[60%] h-[60%] rounded-full bg-[#284e13]/10 blur-[120px]" />
      </div>

      <div className="relative w-full max-w-lg">
        <div className="mb-12 text-center">
          <Link href="/" className="group inline-flex items-center gap-2 mb-8">
            <svg
              width="26"
              height="26"
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              className="shrink-0 text-[#fe9900] transition-colors duration-200 group-hover:text-[#284e13]"
              aria-hidden="true"
            >
              <path
                d="M20.7 3.3C14.9 3.5 10.6 5.5 8.2 8.8c-2.6 3.6-2.6 8.3 1 11.9 3.6-3.4 6.4-7.5 8-12.1-1.1 4.9-3.4 9.5-6.8 13.2 4.9.6 9.4-1.4 11.6-5.1 2-3.3 1.7-7.7-1.3-13.4Z"
                fill="currentColor"
              />
              <path
                d="M9.6 20.9c.2-4.3 1.4-7.8 3.6-10.7-2.9 2.5-5 6.2-5.7 10.6-.1.5.3 1 .8 1.1.6.1 1.2-.3 1.3-1Z"
                fill="currentColor"
                opacity="0.55"
              />
            </svg>
            <span className="text-3xl font-black uppercase tracking-tight text-[#284e13]">КАРКАС</span>
            <span className="text-3xl font-black uppercase tracking-tight text-[#fe9900] transition-colors duration-200 group-hover:text-[#284e13]">
              ТАЙГИ
            </span>
          </Link>
        </div>

        <div className="relative overflow-hidden rounded-[36px] border border-zinc-200 bg-white/80 backdrop-blur-xl p-10 lg:p-16 shadow-2xl shadow-zinc-950/10">
          <div className="absolute left-0 top-0 h-full w-[4px] bg-[#fe9900] opacity-30" />
          
          <form onSubmit={onSubmit} className="grid gap-8">
            <div className="space-y-2">
              <label className="text-[10px] font-black text-zinc-600 uppercase tracking-widest ml-1">Логин</label>
              <input
                className="h-16 w-full rounded-2xl bg-white border border-zinc-200 px-6 text-lg text-zinc-950 outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all placeholder:text-zinc-400 font-medium"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Имя пользователя"
                required
                autoFocus
                ref={loginRef}
                disabled={loading}
              />
            </div>

            <div className="space-y-2">
              <label className="text-[10px] font-black text-zinc-600 uppercase tracking-widest ml-1">Пароль</label>
              <div className="relative">
                <input
                  className="h-16 w-full rounded-2xl bg-white border border-zinc-200 px-6 pr-20 text-lg text-zinc-950 outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all placeholder:text-zinc-400 font-medium"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                  disabled={loading}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 grid h-11 w-11 place-items-center rounded-xl border border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50 transition-all active:scale-95"
                  disabled={loading}
                  aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
                >
                  {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                </button>
              </div>
            </div>

            {error && (
              <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-700 font-black uppercase tracking-widest text-center animate-in fade-in zoom-in-95">
                {error}
              </div>
            )}

            <Button 
              disabled={!canSubmit} 
              type="submit"
              className="h-16 rounded-2xl shadow-xl shadow-[#fe9900]/15 transition-all active:scale-95"
            >
              {loading ? "Вход..." : "Войти в систему"}
            </Button>
          </form>
        </div>
      </div>
    </main>
  );
}
