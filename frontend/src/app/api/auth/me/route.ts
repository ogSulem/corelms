import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { sharedRefresh } from "../_refresh_shared";
import { clearAuthCookies, setAccessCookie, setRefreshCookie } from "../_cookies";

const API_BASE_URL = process.env.CORE_INTERNAL_API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://backend:8000";

export async function GET(request: Request) {
  const jar = await cookies();
  let access = jar.get("core_token")?.value || "";
  const refresh = jar.get("core_refresh")?.value || "";
  let rotation: Extract<Awaited<ReturnType<typeof sharedRefresh>>, { ok: true }> | null = null;

  const finish = (response: NextResponse) => {
    // A refresh-only visit also needs the rotated cookies, not just the JSON user.
    if (rotation) {
      setAccessCookie(response, rotation.access, { upstreamExpiresIn: rotation.expiresIn ?? null });
      if (rotation.nextRefresh) setRefreshCookie(response, rotation.nextRefresh, { refreshExpiresIn: rotation.refreshExpiresIn ?? null });
    }
    response.headers.set("Cache-Control", "private, no-store");
    return response;
  };
  const unavailable = () => finish(NextResponse.json({ error: "Сервис авторизации временно недоступен" }, { status: 503 }));
  const unauthenticated = () => {
    const response = NextResponse.json({ authenticated: false });
    clearAuthCookies(response);
    response.headers.set("Cache-Control", "private, no-store");
    return response;
  };
  const renew = async () => {
    const result = await sharedRefresh({ apiBaseUrl: API_BASE_URL, refreshToken: refresh, proxyHeaders: {
      xRealIp: request.headers.get("x-real-ip"), xForwardedFor: request.headers.get("x-forwarded-for"), forwarded: request.headers.get("forwarded"), userAgent: request.headers.get("user-agent"), origin: request.headers.get("origin"),
    } });
    if (result.ok) { rotation = result; access = result.access; return null; }
    return result.status === 401 || result.status === 403 ? unauthenticated() : unavailable();
  };
  const fetchUser = async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 25000);
    try {
      const headers = new Headers({ Authorization: `Bearer ${access}` });
      for (const name of ["x-real-ip", "x-forwarded-for", "forwarded", "user-agent"]) {
        const value = request.headers.get(name); if (value) headers.set(name, value);
      }
      const response = await fetch(`${API_BASE_URL}/auth/me`, { cache: "no-store", headers, signal: controller.signal });
      return { ok: response.ok, status: response.status, user: response.ok ? await response.json() : null };
    } finally { clearTimeout(timer); }
  };

  if (!access) {
    if (!refresh) return unauthenticated();
    const error = await renew(); if (error) return error;
  }
  try {
    let response = await fetchUser();
    if (response.status === 401 && refresh && !rotation) {
      const error = await renew(); if (error) return error;
      response = await fetchUser();
    }
    if (response.status === 401 || response.status === 403) return unauthenticated();
    if (!response.ok) return unavailable();
    const user = response.user;
    const role = user.role === "manager" ? "admin" : user.role === "employee" ? "user" : user.role;
    return finish(NextResponse.json({ authenticated: true, user: { ...user, role, must_change_password: !!user.must_change_password } }));
  } catch { return unavailable(); }
}
