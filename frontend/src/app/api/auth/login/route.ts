import { NextResponse } from "next/server";

const API_BASE_URL =
  process.env.CORE_INTERNAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://backend:8000";

export async function POST(req: Request) {
  const body = (await req.json()) as { name?: string; password?: string };
  const name = body.name?.trim() || "";
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
    res = await fetch(`${API_BASE_URL}/auth/token`, {
      method: "POST",
      body: form,
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
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

  const data = (await res.json()) as { access_token: string };

  const response = NextResponse.json({ ok: true });
  const isProd = process.env.NODE_ENV === "production";
  const configuredMaxAge = Number.parseInt(process.env.CORE_TOKEN_MAX_AGE_SECONDS || "3600", 10) || 3600;
  const jwtMinutesRaw = Number.parseInt(process.env.JWT_ACCESS_TOKEN_MINUTES || "", 10);
  const jwtMaxAge = Number.isFinite(jwtMinutesRaw) && jwtMinutesRaw > 0 ? jwtMinutesRaw * 60 : null;
  const maxAge = jwtMaxAge ? Math.min(configuredMaxAge, jwtMaxAge) : configuredMaxAge;
  const expires = new Date(Date.now() + maxAge * 1000);
  response.cookies.set({
    name: "core_token",
    value: data.access_token,
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
