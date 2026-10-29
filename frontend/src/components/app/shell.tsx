"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Globe, Send, Youtube } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { AppNav } from "@/components/app/nav";
import { useAuth } from "@/lib/hooks/use-auth";

export function AppShell({ children }: { children?: React.ReactNode }) {
  const { user, loading, error, refresh } = useAuth();
  const authenticated = !!user;
  const homeHref = authenticated ? "/dashboard" : "/";
  const pathname = usePathname();
  const router = useRouter();

  const [loggingOut, setLoggingOut] = React.useState(false);
  const [globalUploadBusy, setGlobalUploadBusy] = React.useState(false);

  const [quickStartOpen, setQuickStartOpen] = React.useState(false);
  const [quickStartVideoFailed, setQuickStartVideoFailed] = React.useState(false);

  const keepAliveInFlightRef = React.useRef(false);
  const lastKeepAliveAtRef = React.useRef(0);
  const keepAliveTimerRef = React.useRef<any>(null);
  const keepAliveFailStreakRef = React.useRef(0);

  React.useEffect(() => {
    function onRefresh(e: any) {
      try {
        const reason = String(e?.detail?.reason || "").trim().toLowerCase();
        if (reason === "keepalive") return;
      } catch {
        // ignore
      }
      void refresh(true);
    }
    window.addEventListener("corelms:refresh-me", onRefresh);
    return () => window.removeEventListener("corelms:refresh-me", onRefresh);
  }, [refresh]);

  React.useEffect(() => {
    if (loading) return;
    if (!authenticated) return;

    const minIntervalMs = 4 * 60_000;

    const tick = async (reason: string) => {
      const now = Date.now();
      if (keepAliveInFlightRef.current) return;
      if (now - lastKeepAliveAtRef.current < minIntervalMs) return;
      keepAliveInFlightRef.current = true;
      try {
        const res = await fetch("/api/auth/refresh", {
          method: "POST",
          cache: "no-store",
          credentials: "include",
          headers: { "x-corelms-reason": reason },
        });
        if (res.ok) {
          lastKeepAliveAtRef.current = now;
          keepAliveFailStreakRef.current = 0;
          window.dispatchEvent(new CustomEvent("corelms:refresh-me", { detail: { reason: "keepalive" } }));
        } else {
          keepAliveFailStreakRef.current = Math.min(10, keepAliveFailStreakRef.current + 1);
        }
      } catch {
        keepAliveFailStreakRef.current = Math.min(10, keepAliveFailStreakRef.current + 1);
      } finally {
        keepAliveInFlightRef.current = false;
      }
    };

    const schedule = () => {
      if (keepAliveTimerRef.current) window.clearInterval(keepAliveTimerRef.current);

      // Base cadence is 10 minutes. If refresh fails repeatedly, slow down to reduce load.
      const baseMs = 10 * 60_000;
      const streak = Math.max(0, Number(keepAliveFailStreakRef.current || 0));
      const multiplier = Math.min(6, 1 + streak);
      const intervalMs = Math.max(baseMs, baseMs * multiplier);
      keepAliveTimerRef.current = window.setInterval(() => void tick("interval"), intervalMs);
    };

    let lastHiddenAt = 0;
    const onFocus = () => void tick("focus");
    const onVisibility = () => {
      const st = document.visibilityState;
      if (st === "hidden") {
        lastHiddenAt = Date.now();
        return;
      }
      if (st === "visible") {
        const hiddenForMs = lastHiddenAt ? Date.now() - lastHiddenAt : 0;
        if (hiddenForMs >= 30_000) void tick("visible");
      }
    };
    const onUpload = () => void tick("upload");

    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("corelms:keepalive", onUpload as EventListener);

    void tick("mount");
    schedule();
    return () => {
      if (keepAliveTimerRef.current) window.clearInterval(keepAliveTimerRef.current);
      window.removeEventListener("focus", onFocus as any);
      document.removeEventListener("visibilitychange", onVisibility as any);
      window.removeEventListener("corelms:keepalive", onUpload as EventListener);
    };
  }, [loading, authenticated, refresh]);

  React.useEffect(() => {
    if (loading) return;
    if (!user) return;
    if (!user.must_change_password) return;
    if (pathname === "/force-password-change") return;
    router.replace("/force-password-change");
  }, [loading, user, pathname, router]);

  React.useEffect(() => {
    if (loading) return;
    if (error) return;
    if (authenticated) return;
    if (pathname === "/" || pathname === "/login" || pathname === "/reset-password") return;
    router.replace("/");
  }, [loading, authenticated, pathname, router, error]);

  React.useEffect(() => {
    if (loading) return;
    if (!authenticated) return;
    if (!user) return;
    if (user.must_change_password) return;
    if (pathname === "/force-password-change") return;

    try {
      const pending = String(localStorage.getItem("corelms:quickstart_pending") || "").trim();
      if (!pending) return;
      const dismissed = String(localStorage.getItem("corelms:quickstart_dismissed_v1") || "").trim();
      if (dismissed) {
        try {
          localStorage.removeItem("corelms:quickstart_pending");
        } catch {
          // ignore
        }
        return;
      }
      setQuickStartOpen(true);
    } catch {
      // ignore
    }
  }, [loading, authenticated, user, pathname]);

  React.useEffect(() => {
    const onOpen = () => { setQuickStartVideoFailed(false); setQuickStartOpen(true); };
    window.addEventListener("corelms:open-quickstart", onOpen as EventListener);
    return () => window.removeEventListener("corelms:open-quickstart", onOpen as EventListener);
  }, []);

  React.useEffect(() => {
    const read = () => {
      try {
        setGlobalUploadBusy(Boolean((window as any).__corelms_upload_busy));
      } catch {
        setGlobalUploadBusy(false);
      }
    };
    const onBusy = () => read();
    read();
    window.addEventListener("corelms:upload-busy", onBusy as EventListener);
    return () => window.removeEventListener("corelms:upload-busy", onBusy as EventListener);
  }, []);

  const closeQuickStart = () => {
    try {
      localStorage.setItem("corelms:quickstart_dismissed_v1", String(Date.now()));
      localStorage.removeItem("corelms:quickstart_pending");
    } catch {
      // ignore
    }
    setQuickStartOpen(false);
  };

  const quickStartAssetId = String(process.env.NEXT_PUBLIC_QUICKSTART_ASSET_ID || "").trim();
  const quickStartVideoUrlRaw = (process.env.NEXT_PUBLIC_QUICKSTART_VIDEO_URL || "").trim();
  let quickStartVideoUrl = quickStartAssetId ? `/api/backend/assets/${encodeURIComponent(quickStartAssetId)}/stream` : quickStartVideoUrlRaw;
  let isYouTube = false;
  if (quickStartVideoUrl && !quickStartAssetId) {
    try {
      const url = new URL(quickStartVideoUrl, "https://lms.invalid");
      if (!["http:", "https:"].includes(url.protocol)) quickStartVideoUrl = "";
      const host = url.hostname.replace(/^www\./, "");
      if (["youtube.com", "youtube-nocookie.com", "youtu.be"].includes(host)) {
        const id = host === "youtu.be" ? url.pathname.slice(1) : url.searchParams.get("v") || url.pathname.split("/").pop() || "";
        isYouTube = /^[a-zA-Z0-9_-]{11}$/.test(id);
        quickStartVideoUrl = isYouTube ? `https://www.youtube-nocookie.com/embed/${id}` : "";
      }
    } catch { quickStartVideoUrl = ""; }
  }

  return (
    <div className="flex min-h-screen min-w-0 flex-col">
      {globalUploadBusy ? (
        <div className="fixed inset-0 z-40">
          <div className="absolute inset-0 bg-zinc-950/15 backdrop-blur-[1px]" />
          <div className="absolute inset-0 flex items-start justify-center p-6 pt-24">
            <div className="w-full max-w-lg rounded-[22px] border border-zinc-200 bg-white/90 shadow-2xl shadow-zinc-950/15">
              <div className="px-6 py-5">
                <div className="text-[10px] font-black uppercase tracking-[0.35em] text-zinc-500">Загрузка</div>
                <div className="mt-2 text-sm font-black uppercase tracking-tight text-zinc-950">
                  Идёт загрузка/импорт модуля. Не закрывай страницу и не переходи по меню.
                </div>
                <div className="mt-2 text-xs font-bold text-zinc-600">Окно можно оставить открытым — процесс продолжится.</div>
              </div>
            </div>
          </div>
        </div>
      ) : null}
      <Modal open={quickStartOpen} title="Как начать обучение" onClose={closeQuickStart} className="max-w-3xl" footer={<div className="flex flex-wrap justify-end gap-3"><Button onClick={closeQuickStart}>Понятно</Button></div>}>
        {quickStartVideoUrl && !quickStartVideoFailed && <div className="mb-6 overflow-hidden rounded-xl bg-zinc-950">{isYouTube ? <iframe className="block aspect-video w-full" src={quickStartVideoUrl} title="Видео: быстрый старт" allow="encrypted-media; picture-in-picture" allowFullScreen loading="lazy" referrerPolicy="strict-origin-when-cross-origin" /> : <video className="block aspect-video w-full" src={quickStartVideoUrl} controls preload="metadata" playsInline onError={() => setQuickStartVideoFailed(true)} />}</div>}
        {quickStartVideoFailed && <p role="status" className="mb-5 text-sm leading-6 text-zinc-600">Видео сейчас недоступно. Начать обучение можно по инструкции ниже.</p>}
        <p className="mb-5 text-sm leading-7 text-zinc-600">Все материалы и результаты собраны в одном месте. Начните с доступного модуля — система подскажет следующий шаг.</p>
        <ol className="space-y-5 text-sm leading-7 text-zinc-600">
          <li><strong className="text-zinc-900">1. Откройте обучение.</strong> На дашборде есть кнопка следующего шага. В разделе «Обучение» можно самостоятельно выбрать модуль.</li>
          <li><strong className="text-zinc-900">2. Изучите материал.</strong> Прочитайте урок, откройте приложенные файлы и нажмите «Я изучил материал». Если предусмотрен тест, переходите к нему после изучения.</li>
          <li><strong className="text-zinc-900">3. Продолжайте в удобном темпе.</strong> Прогресс сохраняется. Обновление файлов не отменяет полученный зачёт — о новых материалах появится отдельная отметка.</li>
        </ol>
      </Modal>

      <a href="#main-content" className="sr-only z-50 rounded-lg bg-white p-3 text-sm focus:not-sr-only focus:fixed focus:left-4 focus:top-3">Перейти к содержимому</a>
      <header className="sticky top-0 z-20 border-b border-zinc-200/80 bg-white/80 backdrop-blur-xl shadow-sm shadow-zinc-950/5">
        <div className="mx-auto grid w-full max-w-[1440px] grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 sm:px-6 xl:grid-cols-[auto_minmax(0,1fr)_auto]">
          <div className="flex min-w-0 items-center justify-start gap-2">
            <a
              href="https://t.me/KarkasTaygiTg"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Telegram"
              title="Telegram"
              className="hidden h-9 w-9 shrink-0 place-items-center 2xl:grid rounded-xl border border-zinc-200 bg-white/85 text-zinc-800 shadow-sm shadow-zinc-950/5 transition-all active:scale-[0.98] hover:bg-white"
            >
              <Send className="h-4 w-4" />
            </a>
            <a
              href="https://vk.com/kt320"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="ВКонтакте"
              title="ВКонтакте"
              className="hidden h-9 w-9 shrink-0 place-items-center 2xl:grid rounded-xl border border-zinc-200 bg-white/85 text-zinc-800 shadow-sm shadow-zinc-950/5 transition-all active:scale-[0.98] hover:bg-white"
            >
              <span className="text-[11px] font-black tracking-widest">VK</span>
            </a>
            <a
              href="http://каркас-тайги.рф"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Сайт"
              title="Сайт"
              className="hidden h-9 w-9 shrink-0 place-items-center 2xl:grid rounded-xl border border-zinc-200 bg-white/85 text-zinc-800 shadow-sm shadow-zinc-950/5 transition-all active:scale-[0.98] hover:bg-white"
            >
              <Globe className="h-4 w-4" />
            </a>
            <a
              href="https://youtube.com/@karkas_t?si=EBpMsSKRLSwAYOgZ"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="YouTube"
              title="YouTube"
              className="hidden h-9 w-9 shrink-0 place-items-center 2xl:grid rounded-xl border border-zinc-200 bg-white/85 text-zinc-800 shadow-sm shadow-zinc-950/5 transition-all active:scale-[0.98] hover:bg-white"
            >
              <Youtube className="h-4 w-4" />
            </a>
            <Link href={homeHref} className="group flex min-w-0 items-center gap-1.5 whitespace-nowrap sm:gap-2">
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
              <span className="text-base font-black uppercase tracking-tight sm:text-[20px] text-[#284e13]">КАРКАС</span>
              <span className="text-base font-black uppercase tracking-tight sm:text-[20px] text-[#fe9900] transition-colors duration-200 group-hover:text-[#284e13]">
                ТАЙГИ
              </span>
            </Link>
          </div>

          <div className="hidden min-w-0 items-center justify-center xl:flex">
            {!loading && authenticated ? <AppNav role={user?.role} authenticated={authenticated} /> : null}
          </div>

          <div className="flex items-center justify-end gap-4">
            {!loading && authenticated && user ? (
              <div className="hidden items-center gap-3 rounded-2xl border border-zinc-200 bg-white/85 px-4 py-2 shadow-sm shadow-zinc-950/5 sm:flex">
                <div className="rounded-xl border border-[#284e13]/20 bg-[#284e13]/10 px-2.5 py-1 text-[10px] font-black uppercase tracking-widest text-[#284e13]">
                  LVL {user.level}
                </div>
                <div className="hidden lg:flex items-center gap-3">
                  <div className="h-4 w-px bg-zinc-200" />
                  <div className="text-[10px] font-black uppercase tracking-widest text-zinc-700">{user.xp} XP</div>
                  <div className="h-4 w-px bg-zinc-200" />
                  <div className="flex items-center gap-1.5 rounded-xl border border-[#fe9900]/25 bg-[#fe9900]/15 px-2.5 py-1 text-[10px] font-black uppercase tracking-widest text-zinc-900">
                    <span>🔥</span>
                    <span>{user.streak}</span>
                  </div>
                </div>
              </div>
            ) : null}
            {!loading && (authenticated ? (
              <Button
                variant="outline"
                size="sm"
                className="rounded-xl font-black uppercase tracking-widest text-[10px] border-zinc-200 bg-white/85 text-zinc-800 shadow-sm shadow-zinc-950/5 hover:bg-zinc-50 hover:text-zinc-950 transition-colors"
                disabled={loggingOut}
                onClick={async () => {
                  if (!window.dispatchEvent(new Event("corelms:before-navigate", { cancelable: true }))) return;
                  setLoggingOut(true);
                  try {
                    const response = await fetch("/api/auth/logout", { method: "POST", signal: AbortSignal.timeout(15000) });
                    if (!response.ok) throw new Error("Не удалось выйти. Проверьте соединение и повторите действие.");
                    const result = await response.json();
                    if (result.session_revoked === false) window.alert("Выход на этом устройстве выполнен, но сервер не подтвердил завершение сеанса. При следующем входе проверьте активные сеансы в личном кабинете.");
                    window.location.href = "/login";
                  } catch (err) {
                    window.dispatchEvent(new Event("corelms:navigation-canceled"));
                    window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "Не удалось выйти", description: err instanceof Error ? err.message : "Повторите действие после восстановления связи." } }));
                  } finally { setLoggingOut(false); }
                }}
              >
                {loggingOut ? "Выходим…" : "Выйти"}
              </Button>
            ) : (
              <Link href="/login">
                <Button size="sm" className="rounded-xl">Войти</Button>
              </Link>
            ))}
          </div>
        </div>

        <div className="mx-auto w-full max-w-[1440px] min-w-0 px-4 pb-3 sm:px-6 xl:hidden">
          {!loading && authenticated ? <AppNav role={user?.role} authenticated={authenticated} /> : null}
        </div>
      </header>
      <main id="main-content" className="min-w-0 flex-1 min-h-0 animate-in fade-in duration-700">{children}</main>



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
