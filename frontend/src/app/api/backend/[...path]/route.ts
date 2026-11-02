import { NextResponse } from "next/server";

import { asciiOrigin } from "../../auth/_request";
import { accessTokens, refreshTokens } from "../../auth/_jar";
import { setAccessCookie, setRefreshCookie } from "../../auth/_cookies";
import { sharedRefresh } from "../../auth/_refresh_shared";


const API_BASE_URL =
  process.env.CORE_INTERNAL_API_BASE_URL ||
  process.env.SDLP_INTERNAL_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://backend:8000";

function parseAllowedOrigins(): string[] {
  // Браузер присылает Origin в punycode, а в .env домен записан кириллицей:
  // сравниваем только ASCII-формы, иначе предпроверка CORS отвечает «нельзя»
  // на собственный же сайт.
  const out = new Set<string>();
  const raw = String(process.env.CORS_ALLOW_ORIGINS || "");
  for (const part of raw.split(",")) {
    const v = asciiOrigin(part);
    if (v) out.add(v);
  }
  const fromPublic = asciiOrigin(process.env.PUBLIC_APP_URL);
  if (fromPublic) out.add(fromPublic);
  return Array.from(out);
}

function isAllowedOrigin(origin: string, allowed: string[]): boolean {
  const o = asciiOrigin(origin);
  if (!o) return false;
  return allowed.includes(o);
}

async function proxy(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = await ctx.params;
  const incomingUrl = new URL(req.url);
  const url = `${API_BASE_URL}/${path.join("/")}${incomingUrl.search || ""}`;

  // Все копии куки: если в браузере осталась старая host-only пара, первую
  // присланную использовать нельзя — это просроченный токен, и пользователь
  // «заходит и сразу вылетает». Порядок — от самого свежего.
  const tokens = accessTokens(req);
  let token = tokens[0] || "";

  const accept = String(req.headers.get("accept") || "");
  const isSse = accept.includes("text/event-stream") || path[path.length - 1] === "events";

  const headers = new Headers(req.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");
  headers.delete("transfer-encoding");
  // API авторизуется токеном в заголовке: сессионные куки наверх не нужны,
  // меньше данных уходит в чужой процесс и его логи.
  headers.delete("cookie");

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

  const isContentUpload = req.method === "POST" && path[0] === "admin" && path[1] === "content" && ["assets", "reimport"].includes(path[path.length - 1]);
  // Частичная загрузка: кусок файла (PUT) и сборка (POST .../complete) идут так же долго,
  // как обычная загрузка: на них нельзя вешать трёхминутный лимит прокси.
  const longUpload = isContentUpload || req.method === "PUT" || path[path.length - 1] === "complete";
  const defaultTimeout = longUpload ? 3600000 : 180000;
  const timeoutMs = Number.parseInt((longUpload ? process.env.BACKEND_PROXY_UPLOAD_TIMEOUT_MS : process.env.BACKEND_PROXY_TIMEOUT_MS) || String(defaultTimeout), 10) || defaultTimeout;
  const ac = new AbortController();
  const t = isSse ? null : setTimeout(() => ac.abort(), Math.max(1000, timeoutMs));

  /** Пробуем токен; 401 — не приговор, сначала пробуем остальные копии куки. */
  const attempt = async (bearer: string): Promise<Response> => {
    headers.set("Authorization", `Bearer ${bearer}`);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (init as any).signal = ac.signal;
    return fetch(url, init);
  };

  let res: Response;
  type Rotation = { access: string; refresh?: string; expiresIn?: number | null; refreshExpiresIn?: number | null };
  const rotation: { value: Rotation | null } = { value: null };

  /** Обновление сессии на сервере: одна попытка на каждую refresh-копию. */
  const rotate = async (): Promise<boolean> => {
    for (const refresh of refreshTokens(req)) {
      const result = await sharedRefresh({ apiBaseUrl: API_BASE_URL, refreshToken: refresh, proxyHeaders: {
        xRealIp: req.headers.get("x-real-ip"), xForwardedFor: req.headers.get("x-forwarded-for"),
        forwarded: req.headers.get("forwarded"), userAgent: req.headers.get("user-agent"), origin: req.headers.get("origin"),
      } });
      if (!result.ok) continue;
      rotation.value = { access: result.access, refresh: result.nextRefresh, expiresIn: result.expiresIn, refreshExpiresIn: result.refreshExpiresIn };
      token = result.access;
      return true;
    }
    return false;
  };

  try {
    // Тело запроса — поток: повторять запрос с ним нельзя (оно уже прочитано).
    // Поэтому для POST/PUT/PATCH/DELETE обновляем сессию ДО отправки, а не после.
    const replayable = req.method === "GET" || req.method === "HEAD";

    if (!token) {
      // Куки доступа нет совсем (браузер её не сохранил): без обновления запрос
      // ушёл бы без авторизации, и пользователя выкинуло бы из кабинета.
      if (!(await rotate())) res = new Response(null, { status: 401 });
      else res = await attempt(token);
    } else {
      res = await attempt(token);
      if (res.status === 401 && replayable) {
        // Просроченный токен из первой копии куки: пробуем остальные.
        for (const candidate of tokens.slice(1)) {
          if (res.status !== 401) break;
          const retry = await attempt(candidate);
          if (retry.status !== 401) res = retry;
        }
        // Сессия ещё жива, если есть refresh-кука: обновляем и повторяем.
        if (res.status === 401 && (await rotate())) res = await attempt(token);
      }
    }
  } catch (err) {
    // Backend недоступен (рестарт, OOM, сеть). Отдаём понятный JSON-контракт,
    // чтобы интерфейс показал причину, а не общее «неизвестно что».
    const reason = err instanceof Error ? err.message : String(err);
    console.error(`[corelms] proxy upstream failure ${req.method} ${url}: ${reason}`);
    const timedOut = ac.signal.aborted;
    return NextResponse.json(
      {
        ok: false,
        error_code: timedOut ? "upstream_timeout" : "upstream_unavailable",
        error_message: timedOut
          ? "Сервер не ответил вовремя. Обновите страницу и повторите действие."
          : "Сервер перезапускается или недоступен. Повторите попытку через минуту.",
      },
      { status: timedOut ? 504 : 502 },
    );
  } finally {
    if (t) clearTimeout(t);
  }

  const responseHeaders = new Headers(res.headers);
  responseHeaders.delete("set-cookie");

  // Персональные данные не должны оседать в кэше браузера или посредника:
  // на общем устройстве «назад» открывало чужой прогресс. Потоковые ответы
  // (видео/PDF, Range) кэшировать разрешаем, но только как приватные.
  if (token) {
    const contentType = String(responseHeaders.get("content-type") || "");
    const isStream = contentType.startsWith("video/") || contentType.startsWith("audio/")
      || contentType.startsWith("image/") || contentType.startsWith("application/pdf")
      || responseHeaders.has("content-range");
    if (isStream) {
      responseHeaders.set("Cache-Control", "private, max-age=0, must-revalidate");
    } else if (!responseHeaders.get("cache-control")) {
      responseHeaders.set("Cache-Control", "private, no-store");
      responseHeaders.set("Pragma", "no-cache");
    }
    responseHeaders.append("Vary", "Cookie, Authorization");
  }

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
    const stream = new Response(res.body, {
      status: res.status,
      headers: responseHeaders,
    });
    if (rotation.value) {
      setAccessCookie(stream, rotation.value.access, { upstreamExpiresIn: rotation.value.expiresIn ?? null, request: req });
      if (rotation.value.refresh) setRefreshCookie(stream, rotation.value.refresh, { refreshExpiresIn: rotation.value.refreshExpiresIn ?? null, request: req });
    }
    return stream;
  }

  const out = new NextResponse(res.body, {
    status: res.status,
    headers: responseHeaders,
  });

  // Обновлённые на сервере токены возвращаем браузеру, чтобы следующая
  // страница уже не нуждалась в повторном обновлении.
  if (rotation.value) {
    setAccessCookie(out, rotation.value.access, { upstreamExpiresIn: rotation.value.expiresIn ?? null, request: req });
    if (rotation.value.refresh) setRefreshCookie(out, rotation.value.refresh, { refreshExpiresIn: rotation.value.refreshExpiresIn ?? null, request: req });
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
  const origin = String(req.headers.get("origin") || "").trim();
  const allowedOrigins = parseAllowedOrigins();
  const allowOrigin = isAllowedOrigin(origin, allowedOrigins) ? origin : "";
  if (!allowOrigin) {
    return new NextResponse(null, { status: 204 });
  }

  const requestedHeadersRaw = String(req.headers.get("access-control-request-headers") || "").trim();
  const requestedHeaders = requestedHeadersRaw
    ? requestedHeadersRaw
        .split(",")
        .map((h) => String(h || "").trim().toLowerCase())
        .filter(Boolean)
    : [];
  const allowedHeaders = new Set(["authorization", "content-type", "x-request-id"]);
  const allowHeaders = requestedHeaders.length
    ? requestedHeaders.filter((h) => allowedHeaders.has(h)).join(", ")
    : "authorization, content-type";

  return new NextResponse(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": allowOrigin,
      "Access-Control-Allow-Credentials": "true",
      "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
      "Access-Control-Allow-Headers": allowHeaders,
      "Access-Control-Max-Age": "86400",
      Vary: "Origin, Access-Control-Request-Headers, Access-Control-Request-Method",
    },
  });
}
