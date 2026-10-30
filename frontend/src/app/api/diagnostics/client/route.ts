import { NextResponse } from "next/server";

import { cookieDomainFor, cookieSecure, normalizeCookieDomain, requestHost, requestIsHttps } from "../../auth/_cookies";

const API_BASE_URL = process.env.CORE_INTERNAL_API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://backend:8000";

/**
 * Что сервер видит от этого браузера. Ничего секретного: только имена куки,
 * адрес, схема и то, какие флаги получит Set-Cookie. Нужно, чтобы «с телефона
 * не входит» превращалось в конкретную причину, а не в догадки.
 */
export async function GET(request: Request) {
  const cookieHeader = request.headers.get("cookie") || "";
  const names = cookieHeader
    .split(";")
    .map((part) => part.split("=")[0]?.trim())
    .filter(Boolean);

  const host = requestHost(request);
  const domain = cookieDomainFor(request);
  const secure = cookieSecure(request);
  const https = requestIsHttps(request);
  const configuredDomain = normalizeCookieDomain(process.env.COOKIE_DOMAIN);
  const configuredSecure = String(process.env.COOKIE_SECURE || "").trim();

  // Версия фронтенда и backend: сразу видно, применился ли деплой.
  let buildTime: string | null = null;
  try {
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    const stat = await fs.stat(path.join(process.cwd(), ".next", "BUILD_ID"));
    buildTime = stat.mtime.toISOString();
  } catch {
    buildTime = null;
  }
  let backendVersion: string | null = null;
  try {
    const response = await fetch(`${API_BASE_URL}/health/version`, { cache: "no-store" });
    if (response.ok) backendVersion = String((await response.json() as { version?: string }).version || "") || null;
  } catch {
    backendVersion = null;
  }

  let backend: { ok: boolean; status: number; detail?: string } = { ok: false, status: 0 };
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    try {
      const response = await fetch(`${API_BASE_URL}/health/live`, { cache: "no-store", signal: controller.signal });
      backend = { ok: response.ok, status: response.status };
    } finally {
      clearTimeout(timer);
    }
  } catch (error) {
    backend = { ok: false, status: 0, detail: error instanceof Error ? error.message : String(error) };
  }

  const hasSession = names.includes("core_token") || names.includes("core_refresh");
  const checks = [
    {
      key: "https",
      ok: https,
      title: "Соединение по HTTPS",
      detail: https
        ? "Страница открыта по HTTPS — пароль и куки передаются защищённо."
        : "Страница открыта по HTTP. Вход возможен, но браузеры и мобильные сети могут блокировать часть функций. Включите HTTPS.",
    },
    {
      key: "cookie_domain",
      ok: !configuredDomain || !!domain || !host,
      title: "Домен куки",
      detail: !configuredDomain
        ? "COOKIE_DOMAIN не задан: кука привязана к текущему адресу — самый безопасный вариант."
        : domain
          ? `COOKIE_DOMAIN=${configuredDomain} подходит к адресу ${host}: браузер сохранит куку.`
          : `COOKIE_DOMAIN=${configuredDomain} не совпадает с адресом ${host}: кука ставится только для текущего адреса, вход всё равно работает.`,
    },
    {
      key: "secure_flag",
      ok: !(secure && !https),
      title: "Флаг Secure",
      detail: secure
        ? "Куки будут с флагом Secure (уходят только по HTTPS)."
        : "Куки без Secure — браузер сохранит их и по HTTP.",
    },
    {
      key: "backend",
      ok: backend.ok,
      title: "Сервис API",
      detail: backend.ok
        ? "Backend отвечает на проверку готовности."
        : `Backend не ответил (${backend.status || "нет ответа"}). Вход невозможен, пока сервис недоступен.`,
    },
    {
      key: "session",
      ok: hasSession,
      title: "Куки сессии в запросе",
      detail: hasSession
        ? `Браузер прислал: ${names.filter((n) => n === "core_token" || n === "core_refresh").join(", ")}.`
        : "Браузер не прислал куки входа. Если вы уже входили — браузер их не сохранил (приватный режим, встроенный браузер мессенджера, «экономия трафика»).",
    },
  ];

  return NextResponse.json({
    ok: true,
    request: {
      url: request.url,
      host,
      forwardedHost: request.headers.get("x-forwarded-host"),
      forwardedProto: request.headers.get("x-forwarded-proto"),
      httpHost: request.headers.get("host"),
      origin: request.headers.get("origin"),
      userAgent: request.headers.get("user-agent"),
      https,
    },
    cookieSettings: {
      configuredDomain: configuredDomain || null,
      configuredSecure: configuredSecure || "auto",
      domain: domain || null,
      hostOnly: !domain,
      secure,
      sameSite: "lax",
    },
    cookies: { names, hasSession },
    backend,
    versions: {
      frontend: String(process.env.APP_VERSION || "dev"),
      frontendBuiltAt: buildTime,
      backend: backendVersion || "неизвестно",
    },
    checks,
  }, { headers: { "Cache-Control": "private, no-store" } });
}
