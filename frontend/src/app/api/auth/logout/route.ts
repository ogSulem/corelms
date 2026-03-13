import * as nextHeaders from "next/headers";
import { NextResponse } from "next/server";
import { clearAuthCookies } from "../_cookies";

const API_BASE_URL =
  process.env.CORE_INTERNAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://backend:8000";

export async function POST() {
  const response = NextResponse.json({ ok: true });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cookieStore = await (nextHeaders as any).cookies();
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
  clearAuthCookies(response);

  return response;
}
