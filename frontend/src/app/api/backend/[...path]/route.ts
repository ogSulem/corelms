import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const API_BASE_URL =
  process.env.CORE_INTERNAL_API_BASE_URL ||
  process.env.SDLP_INTERNAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://backend:8000";

function getCookieValue(cookieHeader: string, name: string): string {
  const raw = String(cookieHeader || "");
  if (!raw) return "";
  const parts = raw.split(";");
  for (const p of parts) {
    const s = p.trim();
    if (!s) continue;
    const eq = s.indexOf("=");
    if (eq <= 0) continue;
    const k = s.slice(0, eq).trim();
    if (k !== name) continue;
    return s.slice(eq + 1).trim();
  }
  return "";
}

async function proxy(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = await ctx.params;
  const incomingUrl = new URL(req.url);
  const url = `${API_BASE_URL}/${path.join("/")}${incomingUrl.search || ""}`;

  const cookieHeader = String(req.headers.get("cookie") || "");
  const tokenFromHeader = getCookieValue(cookieHeader, "core_token");
  const token = tokenFromHeader || (await cookies()).get("core_token")?.value;

  const accept = String(req.headers.get("accept") || "");
  const isSse = accept.includes("text/event-stream") || path[path.length - 1] === "events";

  const headers = new Headers(req.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");
  headers.delete("transfer-encoding");

  // Preserve real client IP through the Next.js proxy.
  // Backend will only trust these headers if TRUST_PROXY_HEADERS=true and request comes from TRUSTED_PROXY_IPS.
  const xri = req.headers.get("x-real-ip");
  const xff = req.headers.get("x-forwarded-for");
  const fwd = req.headers.get("forwarded");
  if (xri) headers.set("x-real-ip", xri);
  if (xff) headers.set("x-forwarded-for", xff);
  if (fwd) headers.set("forwarded", fwd);

  if (token) headers.set("Authorization", `Bearer ${token}`);

  // Use `any` to allow Node.js fetch option `duplex` (not present in TS lib dom typings).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const init: any = {
    method: req.method,
    headers,
    // Important: stream the request body to avoid buffering large uploads (ZIP imports)
    // which can cause ECONNRESET in the Next.js server.
    body: req.method === "GET" || req.method === "HEAD" ? undefined : req.body,
    duplex: "half",
    cache: "no-store",
  };

  const timeoutMs = Number.parseInt(process.env.BACKEND_PROXY_TIMEOUT_MS || "180000", 10) || 180000;
  const ac = new AbortController();
  const t = isSse ? null : setTimeout(() => ac.abort(), Math.max(1000, timeoutMs));

  let res: Response;
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (init as any).signal = ac.signal;
    res = await fetch(url, init);
  } catch {
    return new NextResponse("upstream unavailable", { status: 502 });
  } finally {
    if (t) clearTimeout(t);
  }

  const responseHeaders = new Headers(res.headers);
  responseHeaders.delete("set-cookie");

  if (isSse) {
    if (!res.ok) {
      const rid = responseHeaders.get("x-request-id") || "";
      const code = String(res.status || 0);
      const data = JSON.stringify({ ok: false, error_code: `upstream_${code}`, error_message: "sse upstream error", request_id: rid });
      return new Response(`event: error\ndata: ${data}\n\n`, {
        status: 200,
        headers: {
          "Content-Type": "text/event-stream; charset=utf-8",
          "Cache-Control": "no-cache, no-transform",
          Connection: "keep-alive",
          "X-Accel-Buffering": "no",
        },
      });
    }

    responseHeaders.set("Content-Type", "text/event-stream; charset=utf-8");
    responseHeaders.set("Cache-Control", "no-cache, no-transform");
    responseHeaders.set("Connection", "keep-alive");
    responseHeaders.set("X-Accel-Buffering", "no");
    responseHeaders.delete("content-length");
    return new Response(res.body, {
      status: res.status,
      headers: responseHeaders,
    });
  }

  const out = new NextResponse(res.body, {
    status: res.status,
    headers: responseHeaders,
  });

  if (res.status === 401 && !isSse) {
    const isProd = process.env.NODE_ENV === "production";
    const cookieSecure = String(process.env.COOKIE_SECURE || "").trim()
      ? String(process.env.COOKIE_SECURE || "").trim().toLowerCase() === "true"
      : isProd;
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
  }

  return out;
}

export async function GET(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  return proxy(req, ctx);
}

export async function POST(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  return proxy(req, ctx);
}

export async function PUT(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  return proxy(req, ctx);
}

export async function PATCH(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  return proxy(req, ctx);
}

export async function DELETE(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  return proxy(req, ctx);
}

export async function OPTIONS(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  // Some environments/browsers may send a preflight even for same-origin requests.
  // Do not forward it to FastAPI (which may return 405 for OPTIONS).
  const origin = req.headers.get("origin") || "*";
  const reqHeaders = req.headers.get("access-control-request-headers") || "*";
  const reqMethod = req.headers.get("access-control-request-method") || "*";
  return new NextResponse(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Credentials": "true",
      "Access-Control-Allow-Methods": reqMethod === "*" ? "GET,POST,PUT,PATCH,DELETE,OPTIONS" : reqMethod,
      "Access-Control-Allow-Headers": reqHeaders,
      "Access-Control-Max-Age": "86400",
      Vary: "Origin, Access-Control-Request-Headers, Access-Control-Request-Method",
    },
  });
}
