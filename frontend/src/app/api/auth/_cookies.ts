import type { NextResponse } from "next/server";

function _isProd(): boolean {
  return process.env.NODE_ENV === "production";
}

export function cookieSecure(): boolean {
  const raw = String(process.env.COOKIE_SECURE || "").trim();
  if (raw) return raw.toLowerCase() === "true";
  return _isProd();
}

export function cookieDomain(): string | undefined {
  const v = String(process.env.COOKIE_DOMAIN || "").trim();
  return v || undefined;
}

export function tokenConfiguredMaxAgeSeconds(): number {
  const v = Number.parseInt(process.env.CORE_TOKEN_MAX_AGE_SECONDS || "3600", 10);
  return Number.isFinite(v) && v > 0 ? v : 3600;
}

export function effectiveAccessMaxAgeSeconds(upstreamExpiresIn?: number | null): number {
  const configured = tokenConfiguredMaxAgeSeconds();
  const u = typeof upstreamExpiresIn === "number" && Number.isFinite(upstreamExpiresIn) && upstreamExpiresIn > 0 ? upstreamExpiresIn : null;
  return u ? Math.min(configured, u) : configured;
}

export function setAccessCookie(out: NextResponse, accessToken: string, opts?: { upstreamExpiresIn?: number | null }): void {
  const maxAge = effectiveAccessMaxAgeSeconds(opts?.upstreamExpiresIn ?? null);
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
