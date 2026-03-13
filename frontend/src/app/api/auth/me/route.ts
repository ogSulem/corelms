import * as nextHeaders from "next/headers";
import { NextResponse } from "next/server";
import { sharedRefresh } from "../_refresh_shared";
import { clearAuthCookies, setAccessCookie, setRefreshCookie } from "../_cookies";

const API_BASE_URL =
  process.env.CORE_INTERNAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://backend:8000";

export async function GET(req: Request) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cookieStore = await (nextHeaders as any).cookies();
  const token = cookieStore.get("core_token")?.value;
  const refresh = cookieStore.get("core_refresh")?.value;

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
    const r = await sharedRefresh({
      apiBaseUrl: API_BASE_URL,
      refreshToken: rt,
      proxyHeaders: {
        xRealIp: req.headers.get("x-real-ip"),
        xForwardedFor: req.headers.get("x-forwarded-for"),
        forwarded: req.headers.get("forwarded"),
      },
    });
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
    setAccessCookie(out, args.access, { upstreamExpiresIn: typeof args.expiresIn === "number" ? args.expiresIn : null });
    setRefreshCookie(out, String(args.nextRefresh || ""), {
      refreshExpiresIn: typeof args.refreshExpiresIn === "number" ? args.refreshExpiresIn : null,
    });
  }

  async function fetchMe(accessToken: string): Promise<Response | null> {
    const at = String(accessToken || "").trim();
    if (!at) return null;
    try {
      const headers = new Headers({ Authorization: `Bearer ${at}` });
      const xri = req.headers.get("x-real-ip");
      const xff = req.headers.get("x-forwarded-for");
      const fwd = req.headers.get("forwarded");
      if (xri) headers.set("x-real-ip", xri);
      if (xff) headers.set("x-forwarded-for", xff);
      if (fwd) headers.set("forwarded", fwd);
      return await fetch(`${API_BASE_URL}/auth/me`, {
        cache: "no-store",
        headers,
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
    clearAuthCookies(out);
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
