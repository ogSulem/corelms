import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const API_BASE_URL =
  process.env.CORE_INTERNAL_API_BASE_URL ||
  process.env.SDLP_INTERNAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://backend:8000";

async function proxy(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = await ctx.params;
  const url = `${API_BASE_URL}/${path.join("/")}`;

  const token = (await cookies()).get("core_token")?.value;

  const headers = new Headers(req.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");
  headers.delete("transfer-encoding");

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

  const timeoutMs = Number.parseInt(process.env.BACKEND_PROXY_TIMEOUT_MS || "30000", 10) || 30000;
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), Math.max(1000, timeoutMs));

  let res: Response;
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (init as any).signal = ac.signal;
    res = await fetch(url, init);
  } catch {
    return new NextResponse("upstream unavailable", { status: 502 });
  } finally {
    clearTimeout(t);
  }

  const responseHeaders = new Headers(res.headers);
  responseHeaders.delete("set-cookie");

  return new NextResponse(res.body, {
    status: res.status,
    headers: responseHeaders,
  });
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
