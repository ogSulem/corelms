import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const API_BASE_URL =
  process.env.CORE_INTERNAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://backend:8000";

export async function GET() {
  const cookieStore = await cookies();
  const token = cookieStore.get("core_token")?.value;

  if (!token) {
    return NextResponse.json({ authenticated: false });
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/auth/me`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    return NextResponse.json({ authenticated: false });
  }

  if (!res.ok) {
    const out = NextResponse.json({ authenticated: false });
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
