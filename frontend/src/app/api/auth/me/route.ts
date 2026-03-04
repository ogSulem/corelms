import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { sharedRefresh } from "../_refresh_shared";

const API_BASE_URL =
  process.env.CORE_INTERNAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://backend:8000";

export async function GET() {
  const cookieStore = await cookies();
  const token = cookieStore.get("core_token")?.value;
  const refresh = cookieStore.get("core_refresh")?.value;

  const isProd = process.env.NODE_ENV === "production";
  const cookieSecure = String(process.env.COOKIE_SECURE || "").trim()
    ? String(process.env.COOKIE_SECURE || "").trim().toLowerCase() === "true"
    : isProd;

  async function tryRefresh(): Promise<
    | {
        access: string;
        nextRefresh?: string;
        expiresIn?: number;
        refreshExpiresIn?: number;
      }
    | null
  > {
    const rt = String(refresh || "").trim();
    if (!rt) return null;
    const r = await sharedRefresh({ apiBaseUrl: API_BASE_URL, refreshToken: rt });
    if (!r.ok) return null;
    const expiresIn = Number.isFinite(Number(r.expiresIn)) ? Number(r.expiresIn) : undefined;
    const refreshExpiresIn = Number.isFinite(Number(r.refreshExpiresIn)) ? Number(r.refreshExpiresIn) : undefined;
    return {
      access: r.access,
      nextRefresh: r.nextRefresh,
      expiresIn,
      refreshExpiresIn,
    };
  }

  function setTokenCookies(out: NextResponse, args: { access: string; nextRefresh?: string; expiresIn?: number; refreshExpiresIn?: number }) {
    const configuredMaxAge = Number.parseInt(process.env.CORE_TOKEN_MAX_AGE_SECONDS || "3600", 10) || 3600;
    const upstreamExpiresIn = typeof args.expiresIn === "number" && Number.isFinite(args.expiresIn) ? args.expiresIn : undefined;
    const maxAge = upstreamExpiresIn ? Math.min(configuredMaxAge, upstreamExpiresIn) : configuredMaxAge;
    const expires = new Date(Date.now() + maxAge * 1000);

    out.cookies.set({
      name: "core_token",
      value: String(args.access || "").trim(),
      httpOnly: true,
      sameSite: "lax",
      secure: cookieSecure,
      path: "/",
      maxAge,
      expires,
      priority: "high",
    });

    const rr = String(args.nextRefresh || "").trim();
    if (rr) {
      const refreshMaxAge = typeof args.refreshExpiresIn === "number" && Number.isFinite(args.refreshExpiresIn)
        ? args.refreshExpiresIn
        : 30 * 24 * 60 * 60;
      const refreshExpires = new Date(Date.now() + refreshMaxAge * 1000);
      out.cookies.set({
        name: "core_refresh",
        value: rr,
        httpOnly: true,
        sameSite: "lax",
        secure: cookieSecure,
        path: "/",
        maxAge: refreshMaxAge,
        expires: refreshExpires,
        priority: "high",
      });
    }
  }

  async function fetchMe(accessToken: string): Promise<Response | null> {
    const at = String(accessToken || "").trim();
    if (!at) return null;
    try {
      return await fetch(`${API_BASE_URL}/auth/me`, {
        cache: "no-store",
        headers: { Authorization: `Bearer ${at}` },
      });
    } catch {
      return null;
    }
  }

  let accessToken = String(token || "").trim();
  if (!accessToken && refresh) {
    const rotated = await tryRefresh();
    if (rotated?.access) accessToken = rotated.access;
  }

  if (!accessToken) {
    return NextResponse.json({ authenticated: false });
  }

  let res: Response;
  try {
    const r0 = await fetchMe(accessToken);
    if (!r0) return NextResponse.json({ authenticated: false });
    res = r0;
  } catch {
    return NextResponse.json({ authenticated: false });
  }

  if (!res.ok) {
    // If access is expired, try refresh once (if cookie exists), then retry.
    const rotated = await tryRefresh();
    if (rotated?.access) {
      const r1 = await fetchMe(rotated.access);
      if (r1 && r1.ok) {
        const user = (await r1.json()) as {
          id: string;
          name: string;
          role: string;
          position: string | null;
          xp: number;
          level: number;
          streak: number;
          must_change_password?: boolean;
        };

        const normalizedRole = user.role === "manager" ? "admin" : user.role === "employee" ? "user" : user.role;
        const out = NextResponse.json({
          authenticated: true,
          user: {
            ...user,
            role: normalizedRole,
            must_change_password: !!user.must_change_password,
          },
        });
        setTokenCookies(out, rotated);
        return out;
      }
    }

    const out = NextResponse.json({ authenticated: false });
    out.cookies.set({
      name: "core_token",
      value: "",
      httpOnly: true,
      sameSite: "lax",
      secure: cookieSecure,
      path: "/",
      maxAge: 0,
      expires: new Date(0),
      priority: "high",
    });
    return out;
  }

  const user = (await res.json()) as {
    id: string;
    name: string;
    role: string;
    position: string | null;
    xp: number;
    level: number;
    streak: number;
    must_change_password?: boolean;
  };

  const normalizedRole = user.role === "manager" ? "admin" : user.role === "employee" ? "user" : user.role;

  return NextResponse.json({
    authenticated: true,
    user: {
      ...user,
      role: normalizedRole,
      must_change_password: !!user.must_change_password,
    },
  });
}
