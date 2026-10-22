import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.startsWith("/static") ||
    pathname === "/" ||
    pathname === "/login" ||
    pathname === "/reset-password"
  ) {
    return NextResponse.next();
  }

  const token = req.cookies.get("core_token")?.value;
  const refresh = req.cookies.get("core_refresh")?.value;
  if (!token && !refresh) {
    const url = req.nextUrl.clone();
    url.pathname = "/";
    url.searchParams.set("redirect", pathname);
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}
