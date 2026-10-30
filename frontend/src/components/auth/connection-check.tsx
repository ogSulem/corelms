"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, XCircle } from "lucide-react";

type Check = { key: string; ok: boolean; title: string; detail: string };
type Report = {
  ok: boolean;
  request: { url: string; host: string; https: boolean; userAgent: string | null };
  cookieSettings: { domain: string | null; hostOnly: boolean; secure: boolean; configuredDomain: string | null };
  cookies: { names: string[]; hasSession: boolean };
  backend: { ok: boolean; status: number; detail?: string };
  versions: { frontend: string; frontendBuiltAt: string | null; backend: string };
  checks: Check[];
};

/**
 * «Проверить подключение» на форме входа.
 *
 * Задача — не гадать, почему с телефона не входит, а показать с сервера:
 * схему, домен куки, доступность API и то, какие куки реально пришли.
 */
export function ConnectionCheck({ autoOpen = false }: { autoOpen?: boolean }) {
  const [open, setOpen] = useState(autoOpen);
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setFailure(null);
    try {
      const res = await fetch("/api/diagnostics/client", { cache: "no-store", credentials: "include" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setReport(await res.json() as Report);
    } catch (error) {
      setReport(null);
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }, []);

  // Ошибка входа уже случилась — раскрываем панель, если она ещё закрыта.
  useEffect(() => {
    if (autoOpen) setOpen(true);
  }, [autoOpen]);

  useEffect(() => {
    if (open && !report && !loading && !failure) void load();
  }, [open, report, loading, failure, load]);

  return (
    <div className="mt-8 border-t border-zinc-200 pt-6">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full text-[10px] font-black uppercase tracking-widest text-zinc-500 hover:text-zinc-800 transition-colors"
      >
        {open ? "Скрыть проверку подключения" : "Не получается войти? Проверить подключение"}
      </button>

      {open && (
        <div className="mt-4 grid gap-3 text-left">
          <div className="flex items-center justify-between gap-3">
            <span className="text-[10px] font-black uppercase tracking-widest text-zinc-400">
              Диагностика браузера и сервера
            </span>
            <button
              type="button"
              onClick={() => void load()}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 px-2.5 py-1.5 text-[10px] font-black uppercase tracking-widest text-zinc-600 hover:bg-zinc-50 disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
              Обновить
            </button>
          </div>

          {loading && !report && (
            <p className="text-xs text-zinc-500">Проверяем сервер…</p>
          )}

          {failure && (
            <p className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-semibold text-rose-700">
              Не удалось получить диагностику ({failure}). Значит, сам сайт не отвечает из этого браузера — проверьте соединение или откройте сайт в другом браузере.
            </p>
          )}

          {report && (
            <div className="grid gap-2">
              {report.checks.map((check) => (
                <div
                  key={check.key}
                  className={`flex gap-2 rounded-xl border p-3 text-xs leading-relaxed ${
                    check.ok ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-900"
                  }`}
                >
                  {check.ok ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                  ) : (
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  )}
                  <span>
                    <b className="block font-black uppercase tracking-wider text-[10px]">{check.title}</b>
                    {check.detail}
                  </span>
                </div>
              ))}
              <div className="rounded-xl bg-zinc-50 p-3 font-mono text-[10px] leading-relaxed text-zinc-600 break-all">
                <div>адрес: {report.request.url}</div>
                <div>host: {report.request.host}</div>
                <div>https: {String(report.request.https)}</div>
                <div>кука: {report.cookieSettings.domain ? `domain=${report.cookieSettings.domain}` : "host-only"}</div>
                <div>secure: {String(report.cookieSettings.secure)}</div>
                <div>куки в запросе: {report.cookies.names.length ? report.cookies.names.join(", ") : "—"}</div>
                <div>API: {report.backend.ok ? `ok ${report.backend.status}` : `ошибка ${report.backend.status || "нет ответа"}`}</div>
                <div>версия интерфейса: {report.versions.frontend}{report.versions.frontendBuiltAt ? ` (собран ${report.versions.frontendBuiltAt})` : ""}</div>
                <div>версия API: {report.versions.backend}</div>
              </div>
              <p className="text-[11px] leading-relaxed text-zinc-500">
                Скопируйте этот блок в сообщение о проблеме — по нему видно точную причину.
              </p>
            </div>
          )}

          {report && !report.cookies.hasSession && (
            <p className="flex gap-2 rounded-xl border border-zinc-200 bg-white p-3 text-[11px] leading-relaxed text-zinc-600">
              <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-zinc-400" />
              Если вход уже был — нажмите «Выйти» в кабинете, затем войдите заново: старые куки от прежнего адреса сайта мешают браузеру.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
