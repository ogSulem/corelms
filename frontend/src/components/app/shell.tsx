"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { AppNav } from "@/components/app/nav";
import { useAuth } from "@/lib/hooks/use-auth";

export function AppShell({ children }: { children?: React.ReactNode }) {
  const { user, loading, refresh } = useAuth();
  const authenticated = !!user;
  const homeHref = authenticated ? "/dashboard" : "/";
  const pathname = usePathname();
  const router = useRouter();

  React.useEffect(() => {
    function onRefresh() {
      void refresh();
    }
    window.addEventListener("corelms:refresh-me", onRefresh);
    return () => window.removeEventListener("corelms:refresh-me", onRefresh);
  }, [refresh]);

  React.useEffect(() => {
    if (loading) return;
    if (!user) return;
    if (!user.must_change_password) return;
    if (pathname === "/force-password-change") return;
    router.replace("/force-password-change");
  }, [loading, user, pathname, router]);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-zinc-200/80 bg-white/80 backdrop-blur-xl shadow-sm shadow-zinc-950/5">
        <div className="mx-auto grid max-w-6xl grid-cols-3 items-center px-6 py-4">
          <div className="flex items-center justify-start gap-8">
            <Link href={homeHref} className="group flex items-center gap-2">
              <svg
                width="22"
                height="22"
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
              <span className="text-[20px] font-black uppercase tracking-tight text-[#284e13]">КАРКАС</span>
              <span className="text-[20px] font-black uppercase tracking-tight text-[#fe9900] transition-colors duration-200 group-hover:text-[#284e13]">
                ТАЙГИ
              </span>
            </Link>
          </div>

          <div className="hidden sm:flex items-center justify-center">
            {!loading && authenticated ? <AppNav role={user?.role} authenticated={authenticated} /> : null}
          </div>

          <div className="flex items-center justify-end gap-4">
            {!loading && authenticated && user ? (
              <div className="hidden items-center gap-3 rounded-2xl border border-zinc-200 bg-white/85 px-4 py-2 shadow-sm shadow-zinc-950/5 sm:flex">
                <div className="rounded-xl border border-[#284e13]/20 bg-[#284e13]/10 px-2.5 py-1 text-[10px] font-black uppercase tracking-widest text-[#284e13]">
                  LVL {user.level}
                </div>
                <div className="h-4 w-px bg-zinc-200" />
                <div className="text-[10px] font-black uppercase tracking-widest text-zinc-700">{user.xp} XP</div>
                <div className="h-4 w-px bg-zinc-200" />
                <div className="flex items-center gap-1.5 rounded-xl border border-[#fe9900]/25 bg-[#fe9900]/15 px-2.5 py-1 text-[10px] font-black uppercase tracking-widest text-zinc-900">
                  <span>🔥</span>
                  <span>{user.streak}</span>
                </div>
              </div>
            ) : null}
            {!loading && (authenticated ? (
              <Button
                variant="outline"
                size="sm"
                className="rounded-xl font-black uppercase tracking-widest text-[10px] border-zinc-200 bg-white/85 text-zinc-800 shadow-sm shadow-zinc-950/5 hover:bg-zinc-50 hover:text-zinc-950 transition-colors"
                onClick={async () => {
                  await fetch("/api/auth/logout", { method: "POST" });
                  window.location.href = "/login";
                }}
              >
                Выйти
              </Button>
            ) : (
              <Link href="/login">
                <Button size="sm" className="rounded-xl">Войти</Button>
              </Link>
            ))}
          </div>
        </div>

        <div className="mx-auto max-w-6xl px-6 pb-4 sm:hidden">
          {!loading && authenticated ? <AppNav role={user?.role} authenticated={authenticated} /> : null}
        </div>
      </header>
      <main className="animate-in fade-in duration-700">{children}</main>

      <button
        type="button"
        aria-label="Частые вопросы"
        title="Частые вопросы"
        onClick={() => router.push("/faq")}
        className={
          "fixed right-6 bottom-6 z-50 h-14 w-14 rounded-full " +
          "bg-[#fe9900] shadow-2xl shadow-[#fe9900]/25 border border-[#fe9900]/30 ring-4 ring-[#fe9900]/10 " +
          "grid place-items-center transition-all active:scale-[0.98] hover:translate-y-[-1px] hover:ring-[#fe9900]/15"
        }
      >
        <svg
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="text-[#284e13]"
          aria-hidden="true"
        >
          <path
            d="M12 18h.01"
            stroke="currentColor"
            strokeWidth="2.6"
            strokeLinecap="round"
          />
          <path
            d="M9.25 9.5a2.75 2.75 0 1 1 4.2 2.33c-.84.56-1.45 1.15-1.45 2.17v.25"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10Z"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      <footer className="border-t border-zinc-200/80 bg-white/70 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-6 py-8 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-[9px] font-black uppercase tracking-[0.35em] text-zinc-600">
            © {new Date().getFullYear()} Каркас Тайги • LMS
          </div>
          <div className="text-[9px] font-black uppercase tracking-[0.35em] text-zinc-600">
            Внутренний продукт компании • Все права защищены
          </div>
        </div>
      </footer>
    </div>
  );
}
