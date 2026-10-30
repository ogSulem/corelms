import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { clearAuthCookies } from "../_cookies";
import { allowedAuthRequest, authHeaders } from "../_request";

const API_BASE_URL = process.env.CORE_INTERNAL_API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://backend:8000";

export async function POST(request: Request) {
  if (!allowedAuthRequest(request)) return NextResponse.json({ ok: false, error_code: "invalid_origin" }, { status: 403 });
  const jar = await cookies();
  const refresh = jar.get("core_refresh")?.value;
  const access = jar.get("core_token")?.value;
  let revoked = !refresh && !access;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    if (refresh || access) {
      const headers = authHeaders(request, { Authorization: `Bearer ${refresh || access}` });
      if (access) headers.set("Cookie", `core_token=${encodeURIComponent(access)}`);
      const response = await fetch(`${API_BASE_URL}/auth/logout`, {
        method: "POST", cache: "no-store", signal: controller.signal,
        headers,
      });
      revoked = response.ok;
    }
  } catch { /* Local logout must still work during an API outage. */ }
  finally { clearTimeout(timer); }
  const response = NextResponse.json({ ok: true, session_revoked: revoked }, { headers: { "Cache-Control": "private, no-store" } });
  clearAuthCookies(response, request);
  return response;
}
