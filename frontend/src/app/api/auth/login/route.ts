import { NextResponse } from "next/server";
import { setAccessCookie, setRefreshCookie } from "../_cookies";

const API_BASE_URL =
  process.env.CORE_INTERNAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://backend:8000";

export async function POST(req: Request) {
  const body = (await req.json()) as { name?: string; email?: string; password?: string };
  const name = (body.email ?? body.name)?.trim() || "";
  const password = body.password || "";

  if (!name || !password) {
    return NextResponse.json(
      { ok: false, error_code: "invalid_payload", error_message: "Invalid payload" },
      { status: 400 }
    );
  }

  const form = new URLSearchParams();
  form.set("username", name);
  form.set("password", password);

  let res: Response;
  try {
    const headers = new Headers({ "Content-Type": "application/x-www-form-urlencoded" });
    const xri = req.headers.get("x-real-ip");
    const xff = req.headers.get("x-forwarded-for");
    const fwd = req.headers.get("forwarded");
    if (xri) headers.set("x-real-ip", xri);
    if (xff) headers.set("x-forwarded-for", xff);
    if (fwd) headers.set("forwarded", fwd);
    res = await fetch(`${API_BASE_URL}/auth/token`, {
      method: "POST",
      body: form,
      headers,
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      { ok: false, error_code: "upstream_unavailable", error_message: "Auth service unavailable" },
      { status: 502 }
    );
  }

  if (!res.ok) {
    const status = res.status || 401;
    const code = status === 401 ? "invalid_credentials" : "upstream_error";
    return NextResponse.json(
      { ok: false, error_code: code, error_message: status === 401 ? "invalid credentials" : "Login failed" },
      { status }
    );
  }

  const data = (await res.json()) as { access_token: string; refresh_token?: string | null; expires_in?: number | null; refresh_expires_in?: number | null };

  const response = NextResponse.json({ ok: true });
  const upstreamExpiresIn = Number.isFinite(Number(data.expires_in)) ? Number(data.expires_in) : null;
  setAccessCookie(response, String(data.access_token || ""), { upstreamExpiresIn });

  const refresh = String(data.refresh_token || "").trim();
  setRefreshCookie(response, refresh, {
    refreshExpiresIn: Number.isFinite(Number(data.refresh_expires_in)) ? Number(data.refresh_expires_in) : null,
  });

  return response;
}
