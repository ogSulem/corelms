import * as nextHeaders from "next/headers";
import { NextResponse } from "next/server";
import { sharedRefresh } from "../_refresh_shared";
import { clearAuthCookies, setAccessCookie, setRefreshCookie } from "../_cookies";

const API_BASE_URL =
  process.env.CORE_INTERNAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://backend:8000";

export async function POST(req: Request) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cookieStore = await (nextHeaders as any).cookies();
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
    clearAuthCookies(out);
    return out;
  }

  const access = String(result.access || "").trim();

  const response = NextResponse.json({ ok: true });
  setAccessCookie(response, access, {
    upstreamExpiresIn: Number.isFinite(Number(result.expiresIn)) ? Number(result.expiresIn) : null,
  });

  setRefreshCookie(response, String(result.nextRefresh || ""), {
    refreshExpiresIn: Number.isFinite(Number(result.refreshExpiresIn)) ? Number(result.refreshExpiresIn) : null,
  });

  return response;
}
