import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const API_BASE_URL =
  process.env.CORE_INTERNAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://backend:8000";

export async function POST() {
  const cookieStore = await cookies();
  const token = cookieStore.get("core_token")?.value;

  if (!token) {
    return NextResponse.json({ ok: false, error_code: "not_authenticated" }, { status: 401 });
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    return NextResponse.json({ ok: false, error_code: "upstream_unavailable" }, { status: 502 });
  }

  if (!res.ok) {
    const out = NextResponse.json({ ok: false, error_code: "refresh_failed" }, { status: 401 });
    const isProd = process.env.NODE_ENV === "production";
    out.cookies.set({
      name: "core_token",
      value: "",
      httpOnly: true,
      sameSite: "lax",
      secure: isProd,
      path: "/",
      maxAge: 0,
      expires: new Date(0),
      priority: "high",
    });
    return out;
  }

  const data = (await res.json()) as { access_token: string; expires_in?: number | null };
  const access = String(data?.access_token || "").trim();
  if (!access) {
    return NextResponse.json({ ok: false, error_code: "refresh_failed" }, { status: 401 });
  }

  const configuredMaxAge = Number.parseInt(process.env.CORE_TOKEN_MAX_AGE_SECONDS || "3600", 10) || 3600;
  const upstreamExpiresIn = Number.isFinite(Number(data.expires_in)) ? Number(data.expires_in) : null;
  const maxAge = upstreamExpiresIn ? Math.min(configuredMaxAge, upstreamExpiresIn) : configuredMaxAge;
  const expires = new Date(Date.now() + maxAge * 1000);

  const response = NextResponse.json({ ok: true });
  const isProd = process.env.NODE_ENV === "production";
  response.cookies.set({
    name: "core_token",
    value: access,
    httpOnly: true,
    sameSite: "lax",
    secure: isProd,
    path: "/",
    maxAge,
    expires,
    priority: "high",
  });

  return response;
}
