import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { sharedRefresh } from "../_refresh_shared";

const API_BASE_URL =
  process.env.CORE_INTERNAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://backend:8000";

export async function POST(req: Request) {
  const cookieStore = await cookies();
  const refresh = cookieStore.get("core_refresh")?.value;

  if (!refresh) {
    return NextResponse.json({ ok: false, error_code: "not_authenticated" }, { status: 401 });
  }

  const result = await sharedRefresh({
    apiBaseUrl: API_BASE_URL,
    refreshToken: String(refresh || ""),
    proxyHeaders: {
      xRealIp: req.headers.get("x-real-ip"),
      xForwardedFor: req.headers.get("x-forwarded-for"),
      forwarded: req.headers.get("forwarded"),
    },
  });

  if (!result.ok) {
    if (result.status === 502) {
      return NextResponse.json({ ok: false, error_code: "upstream_unavailable" }, { status: 502 });
    }

    const out = NextResponse.json({ ok: false, error_code: "refresh_failed" }, { status: 401 });
    const isProd = process.env.NODE_ENV === "production";
    const cookieSecure = String(process.env.COOKIE_SECURE || "").trim()
      ? String(process.env.COOKIE_SECURE || "").trim().toLowerCase() === "true"
      : isProd;
    const cookieDomain = String(process.env.COOKIE_DOMAIN || "").trim() || undefined;
    out.cookies.set({
      name: "core_token",
      value: "",
      httpOnly: true,
      sameSite: "lax",
      secure: cookieSecure,
      domain: cookieDomain,
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
      secure: cookieSecure,
      domain: cookieDomain,
      path: "/",
      maxAge: 0,
      expires: new Date(0),
      priority: "high",
    });
    return out;
  }

  const access = String(result.access || "").trim();

  const configuredMaxAge = Number.parseInt(process.env.CORE_TOKEN_MAX_AGE_SECONDS || "3600", 10) || 3600;
  const upstreamExpiresIn = Number.isFinite(Number(result.expiresIn)) ? Number(result.expiresIn) : null;
  const maxAge = upstreamExpiresIn ? Math.min(configuredMaxAge, upstreamExpiresIn) : configuredMaxAge;
  const expires = new Date(Date.now() + maxAge * 1000);

  const response = NextResponse.json({ ok: true });
  const isProd = process.env.NODE_ENV === "production";
  const cookieSecure = String(process.env.COOKIE_SECURE || "").trim()
    ? String(process.env.COOKIE_SECURE || "").trim().toLowerCase() === "true"
    : isProd;
  const cookieDomain = String(process.env.COOKIE_DOMAIN || "").trim() || undefined;
  response.cookies.set({
    name: "core_token",
    value: access,
    httpOnly: true,
    sameSite: "lax",
    secure: cookieSecure,
    domain: cookieDomain,
    path: "/",
    maxAge,
    expires,
    priority: "high",
  });

  const nextRefresh = String(result.nextRefresh || "").trim();
  if (nextRefresh) {
    const refreshMaxAge = Number.isFinite(Number(result.refreshExpiresIn)) ? Number(result.refreshExpiresIn) : 30 * 24 * 60 * 60;
    const refreshExpires = new Date(Date.now() + refreshMaxAge * 1000);
    response.cookies.set({
      name: "core_refresh",
      value: nextRefresh,
      httpOnly: true,
      sameSite: "lax",
      secure: cookieSecure,
      domain: cookieDomain,
      path: "/",
      maxAge: refreshMaxAge,
      expires: refreshExpires,
      priority: "high",
    });
  }

  return response;
}
