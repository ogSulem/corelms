import type { NextResponse } from "next/server";
import { domainToASCII } from "url";

function _isProd(): boolean {
  return process.env.NODE_ENV === "production";
}

function cookieSecure(): boolean {
  const raw = String(process.env.COOKIE_SECURE || "").trim();
  if (raw) return raw.toLowerCase() === "true";
  return _isProd();
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

export function setAccessCookie(out: NextResponse, accessToken: string, opts?: { upstreamExpiresIn?: number | null }): void {
  const maxAge = effectiveAccessMaxAgeSeconds(opts?.upstreamExpiresIn ?? null);
  if (cookieDomain()) expireHostOnlyCookie(out as unknown as { cookies: { set: (c: Record<string, unknown>) => unknown } }, "core_token");
  out.cookies.set({
    name: "core_token",
    value: String(accessToken || "").trim(),
    httpOnly: true,
    sameSite: "lax",
    secure: cookieSecure(),
    domain: cookieDomain(),
    path: "/",
    maxAge,
    expires: new Date(Date.now() + maxAge * 1000),
    priority: "high",
  });
}

export function setRefreshCookie(out: NextResponse, refreshToken: string, opts?: { refreshExpiresIn?: number | null }): void {
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
    secure: cookieSecure(),
    domain: cookieDomain(),
    path: "/",
    maxAge: ttl,
    expires: new Date(Date.now() + ttl * 1000),
    priority: "high",
  });
}

export function clearAuthCookies(out: NextResponse): void {
  out.cookies.set({
    name: "core_token",
    value: "",
    httpOnly: true,
    sameSite: "lax",
    secure: cookieSecure(),
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
    secure: cookieSecure(),
    domain: cookieDomain(),
    path: "/",
    maxAge: 0,
    expires: new Date(0),
    priority: "high",
  });
}
