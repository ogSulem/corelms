import { NextResponse } from "next/server";
import { clearAuthCookies } from "../_cookies";
import { allowedAuthRequest, authHeaders } from "../_request";
import { accessTokens, refreshTokens } from "../_jar";

const API_BASE_URL = process.env.CORE_INTERNAL_API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://backend:8000";

export async function POST(request: Request) {
  if (!allowedAuthRequest(request)) return NextResponse.json({ ok: false, error_code: "invalid_origin" }, { status: 403 });
  // Отзываем все копии: выход должен гасить и старую host-only, и доменную.
  const refreshList = refreshTokens(request);
  const accessList = accessTokens(request);
  const refresh = refreshList[0];
  const access = accessList[0];
  let revoked = !refresh && !access;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    // Отзываем каждую копию refresh-куки: если в браузере остались дубли,
    // одного запроса недостаточно и сессия продолжала жить.
    const tokens = refreshList.length ? refreshList : accessList;
    if (tokens.length) {
      revoked = true;
      for (const token of tokens) {
        const headers = authHeaders(request, { Authorization: `Bearer ${token}` });
        const response = await fetch(`${API_BASE_URL}/auth/logout`, {
          method: "POST", cache: "no-store", signal: controller.signal,
          headers,
        });
        // Отзыв уже погашенной сессии — тоже успех: цель выхода достигнута.
        if (!response.ok && response.status !== 401) revoked = false;
      }
    }
  } catch { /* Local logout must still work during an API outage. */ }
  finally { clearTimeout(timer); }
  const response = NextResponse.json({ ok: true, session_revoked: revoked }, { headers: { "Cache-Control": "private, no-store" } });
  clearAuthCookies(response, request);
  return response;
}
