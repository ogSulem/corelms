import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const API_BASE_URL =
  process.env.CORE_INTERNAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://backend:8000";

export async function POST() {
  const response = NextResponse.json({ ok: true });
  const isProd = process.env.NODE_ENV === "production";
  const cookieStore = await cookies();
  const refresh = cookieStore.get("core_refresh")?.value;
  if (refresh) {
    try {
      await fetch(`${API_BASE_URL}/auth/logout`, {
        method: "POST",
        cache: "no-store",
        headers: { Authorization: `Bearer ${refresh}` },
      });
    } catch {
      // ignore
    }
  }
  response.cookies.set({
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
  response.cookies.set({
    name: "core_refresh",
    value: "",
    httpOnly: true,
    sameSite: "lax",
    secure: isProd,
    path: "/",
    maxAge: 0,
    expires: new Date(0),
    priority: "high",
  });

  return response;
}
