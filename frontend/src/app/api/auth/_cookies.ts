import type { NextResponse } from "next/server";
import { domainToASCII } from "url";

function _isProd(): boolean {
  return process.env.NODE_ENV === "production";
}

/**
 * Защищено ли соединение на самом деле. За nginx/Caddy смотрим X-Forwarded-Proto,
 * иначе — на протокол самого запроса.
 */
export function requestIsHttps(request?: Request | null): boolean {
  if (!request) return false;
  const forwarded = String(request.headers.get("x-forwarded-proto") || "").split(",")[0].trim().toLowerCase();
  if (forwarded === "https") return true;
  if (forwarded === "http") return false;
  try {
    return new URL(request.url).protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * Флаг Secure только для HTTPS.
 *
 * Раньше он включался по NODE_ENV=production, поэтому на `http://IP:8888`
 * браузер молча выбрасывал куку: вход «проходил», а следующий же запрос
 * получал 401 — пользователя возвращало на страницу входа. На десктопе это
 * было незаметно, если он открывал https-домен, а мобильный заходил по IP.
 * Cookie без Secure на HTTP работает, а на HTTPS Secure выставляется как надо.
 */
function cookieSecure(request?: Request | null): boolean {
  const raw = String(process.env.COOKIE_SECURE || "").trim();
  const enforced = raw ? raw.toLowerCase() === "true" : _isProd();
  if (!enforced) return false;
  // Без контекста запроса (внутренние вызовы, тесты) доверяем настройке.
  if (!request) return true;
  return requestIsHttps(request);
}

/**
 * Кука должна получать ASCII-домен: браузер хранит только punycode.
 * Кириллический COOKIE_DOMAIN (edu.каркастайги.рф) раньше молча отбрасывался,
 * из-за чего кука становилась host-only без всякого предупреждения.
 */
export function normalizeCookieDomain(raw: string | null | undefined): string | undefined {
  const value = String(raw || "").trim().replace(/^\./, "");
  if (!value) return undefined;
  if (/^[\x00-\x7F]+$/.test(value)) return value;
  const ascii = domainToASCII(value);
  return ascii || undefined;
}

function cookieDomain(): string | undefined {
  return normalizeCookieDomain(process.env.COOKIE_DOMAIN);
}

/**
 * Когда включён COOKIE_DOMAIN, у пользователей ещё может лежать старая
 * host-only кука с тем же именем: браузер пришлёт обе, и сервер может
 * прочитать устаревшую. Гасим host-only копию при каждой записи.
 */
export function expireHostOnlyCookie(out: { cookies: { set: (c: Record<string, unknown>) => unknown } }, name: string): void {
  out.cookies.set({ name, value: "", path: "/", maxAge: 0, expires: new Date(0) });
}

function tokenConfiguredMaxAgeSeconds(): number {
  const v = Number.parseInt(process.env.CORE_TOKEN_MAX_AGE_SECONDS || "3600", 10);
  return Number.isFinite(v) && v > 0 ? v : 3600;
}

function effectiveAccessMaxAgeSeconds(upstreamExpiresIn?: number | null): number {
  const configured = tokenConfiguredMaxAgeSeconds();
  const u = typeof upstreamExpiresIn === "number" && Number.isFinite(upstreamExpiresIn) && upstreamExpiresIn > 0 ? upstreamExpiresIn : null;
  return u ? Math.min(configured, u) : configured;
}

export function setAccessCookie(out: NextResponse, accessToken: string, opts?: { upstreamExpiresIn?: number | null; request?: Request | null }): void {
  const maxAge = effectiveAccessMaxAgeSeconds(opts?.upstreamExpiresIn ?? null);
  if (cookieDomain()) expireHostOnlyCookie(out as unknown as { cookies: { set: (c: Record<string, unknown>) => unknown } }, "core_token");
  out.cookies.set({
    name: "core_token",
    value: String(accessToken || "").trim(),
    httpOnly: true,
    sameSite: "lax",
    secure: cookieSecure(opts?.request),
    domain: cookieDomain(),
    path: "/",
    maxAge,
    expires: new Date(Date.now() + maxAge * 1000),
    priority: "high",
  });
}

export function setRefreshCookie(out: NextResponse, refreshToken: string, opts?: { refreshExpiresIn?: number | null; request?: Request | null }): void {
  const v = String(refreshToken || "").trim();
  if (!v) return;
  const ttl =
    typeof opts?.refreshExpiresIn === "number" && Number.isFinite(opts.refreshExpiresIn) && opts.refreshExpiresIn > 0
      ? opts.refreshExpiresIn
      : 30 * 24 * 60 * 60;
  if (cookieDomain()) expireHostOnlyCookie(out as unknown as { cookies: { set: (c: Record<string, unknown>) => unknown } }, "core_refresh");
  out.cookies.set({
    name: "core_refresh",
    value: v,
    httpOnly: true,
    sameSite: "lax",
    secure: cookieSecure(opts?.request),
    domain: cookieDomain(),
    path: "/",
    maxAge: ttl,
    expires: new Date(Date.now() + ttl * 1000),
    priority: "high",
  });
}

export function clearAuthCookies(out: NextResponse, request?: Request | null): void {
  out.cookies.set({
    name: "core_token",
    value: "",
    httpOnly: true,
    sameSite: "lax",
    secure: cookieSecure(request),
    domain: cookieDomain(),
    path: "/",
    maxAge: 0,
    expires: new Date(0),
    priority: "high",
  });
  out.cookies.set({
    name: "core_refresh",
    value: "",
    httpOnly: true,
    sameSite: "lax",
    secure: cookieSecure(request),
    domain: cookieDomain(),
    path: "/",
    maxAge: 0,
    expires: new Date(0),
    priority: "high",
  });
}
