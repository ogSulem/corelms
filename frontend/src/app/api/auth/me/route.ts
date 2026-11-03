import { NextResponse } from "next/server";
import { sharedRefresh } from "../_refresh_shared";
import { clearAuthCookies, setAccessCookie, setRefreshCookie } from "../_cookies";
import { accessTokens, refreshTokens } from "../_jar";

const API_BASE_URL = process.env.CORE_INTERNAL_API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://backend:8000";

export async function GET(request: Request) {
  // Читаем ВСЕ копии кук: у пользователя могли остаться старые host-only куки
  // рядом с доменными. `cookies().get()` вернул бы первую (самую старую) — и
  // «вход» превращался в «зашёл и вылетел».
  const accessCandidates = accessTokens(request);
  const refreshCandidates = refreshTokens(request);
  let access = accessCandidates[0] || "";
  let rotation: Extract<Awaited<ReturnType<typeof sharedRefresh>>, { ok: true }> | null = null;

  const finish = (response: NextResponse) => {
    // A refresh-only visit also needs the rotated cookies, not just the JSON user.
    if (rotation) {
      setAccessCookie(response, rotation.access, { upstreamExpiresIn: rotation.expiresIn ?? null, request });
      if (rotation.nextRefresh) setRefreshCookie(response, rotation.nextRefresh, { refreshExpiresIn: rotation.refreshExpiresIn ?? null, request });
    }
    response.headers.set("Cache-Control", "private, no-store");
    return response;
  };
  const unavailable = () => finish(NextResponse.json({ error: "Сервис авторизации временно недоступен" }, { status: 503 }));
  const unauthenticated = () => {
    const response = NextResponse.json({ authenticated: false });
    clearAuthCookies(response, request);
    response.headers.set("Cache-Control", "private, no-store");
    return response;
  };
  /**
   * Обновление сессии: пробуем все refresh-копии, а не только первую.
   * Если сервер ответил 401 на текущую, следующая копия может быть рабочей.
   */
  const renew = async () => {
    for (const token of refreshCandidates) {
      const result = await sharedRefresh({ apiBaseUrl: API_BASE_URL, refreshToken: token, proxyHeaders: {
        xRealIp: request.headers.get("x-real-ip"), xForwardedFor: request.headers.get("x-forwarded-for"), userAgent: request.headers.get("user-agent"), origin: request.headers.get("origin"),
      } });
      if (result.ok) { rotation = result; access = result.access; return null; }
      if (result.status !== 401 && result.status !== 403) return unavailable();
    }
    return refreshCandidates.length ? unauthenticated() : null;
  };
  const fetchUser = async (token: string) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 25000);
    try {
      const headers = new Headers({ Authorization: `Bearer ${token}` });
      for (const name of ["x-real-ip", "x-forwarded-for", "user-agent"]) {
        const value = request.headers.get(name); if (value) headers.set(name, value);
      }
      const response = await fetch(`${API_BASE_URL}/auth/me`, { cache: "no-store", headers, signal: controller.signal });
      return { ok: response.ok, status: response.status, user: response.ok ? await response.json() : null };
    } finally { clearTimeout(timer); }
  };

  if (!access) {
    if (!refreshCandidates.length) return unauthenticated();
    const error = await renew(); if (error) return error;
  }
  try {
    let response = await fetchUser(access);
    // Просроченный или чужой токен из дубля куки: пробуем остальные копии,
    // затем — обновление. Пользователь не должен вылетать из-за старой куки.
    if (response.status === 401) {
      for (const token of accessCandidates.slice(1)) {
        if (!token) continue;
        const retry = await fetchUser(token);
        if (retry.ok) { response = retry; access = token; break; }
        if (retry.status !== 401 && retry.status !== 403) return unavailable();
      }
    }
    if (response.status === 401 && refreshCandidates.length && !rotation) {
      const error = await renew(); if (error) return error;
      response = await fetchUser(access);
    }
    if (response.status === 401 || response.status === 403) return unauthenticated();
    if (!response.ok) return unavailable();
    const user = response.user;
    // partner — та же роль, что employee (обучающийся без прав админа), поэтому
    // наружу отдаём одно значение: иначе тип User.role расходится с данными.
    const role = user.role === "manager" ? "admin"
      : user.role === "partner" || user.role === "employee" ? "employee"
      : user.role;
    return finish(NextResponse.json({ authenticated: true, user: { ...user, role, must_change_password: !!user.must_change_password } }));
  } catch { return unavailable(); }
}
