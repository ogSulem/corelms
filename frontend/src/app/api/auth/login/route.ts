import { NextResponse } from "next/server";
import { setAccessCookie, setRefreshCookie } from "../_cookies";
import { allowedAuthRequest, asciiOrigin, authHeaders, loginPayload, passwordTooLong } from "../_request";

const API_BASE_URL = process.env.CORE_INTERNAL_API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://backend:8000";
const error = (status: number, error_code: string, error_message: string) =>
  NextResponse.json({ ok: false, error_code, error_message }, { status, headers: { "Cache-Control": "private, no-store" } });

/** Что именно ответил backend: разбираем контракт ошибки, не теряя причину. */
async function upstreamReason(response: Response): Promise<{ code: string; message: string }> {
  try {
    const data = await response.json() as Record<string, unknown>;
    const detail = data?.detail as Record<string, unknown> | string | undefined;
    const code = String(data?.error_code || (typeof detail === "object" && detail ? detail.error_code : "") || "");
    const message = String(data?.error_message || (typeof detail === "object" && detail ? detail.error_message : typeof detail === "string" ? detail : "") || "");
    return { code, message };
  } catch {
    return { code: "", message: "" };
  }
}

export async function POST(req: Request) {
  const origin = req.headers.get("origin");
  if (!allowedAuthRequest(req)) {
    // В журнал — что пришло и что разрешено: иначе «вход не работает» не отладить.
    console.warn(
      `[corelms] login rejected by origin check: origin=${origin || "—"} ascii=${asciiOrigin(origin) || "—"} ` +
      `host=${req.headers.get("host") || "—"} public_app_url=${process.env.PUBLIC_APP_URL || "—"} ` +
      `cors=${process.env.CORS_ALLOW_ORIGINS || "—"}`,
    );
    return error(403, "invalid_origin", "Сервер отклонил источник запроса. Адрес сайта в настройках сервера (PUBLIC_APP_URL / CORS_ALLOW_ORIGINS) не совпадает с адресом, по которому открыт сайт.");
  }
  let body: unknown = null;
  try { body = await req.json(); }
  catch { return error(400, "invalid_payload", "Проверьте логин и пароль"); }
  const payload = loginPayload(body);
  if (!payload) {
    if (passwordTooLong((body as { password?: unknown } | null)?.password)) {
      return error(400, "password_too_long", "Пароль длиннее 72 байт — проверьте раскладку и Caps Lock.");
    }
    return error(400, "invalid_payload", "Введите логин и пароль.");
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 25000);
  try {
    const upstream = await fetch(`${API_BASE_URL}/auth/token`, {
      method: "POST", body: new URLSearchParams(payload), cache: "no-store", signal: controller.signal,
      headers: authHeaders(req, { "Content-Type": "application/x-www-form-urlencoded" }),
    });
    if (!upstream.ok) {
      const { code, message } = await upstreamReason(upstream);
      console.warn(`[corelms] login upstream ${upstream.status} code=${code || "—"} message=${message || "—"} origin=${asciiOrigin(origin) || "—"}`);
      const response = error(
        upstream.status,
        upstream.status === 401 ? "invalid_credentials" : code === "invalid_origin" ? "invalid_origin" : upstream.status === 429 ? "rate_limited" : "upstream_error",
        upstream.status === 401 ? "Неверный логин или пароль"
          : code === "invalid_origin" ? "Сервер отклонил источник запроса: адрес сайта в его настройках не совпадает с текущим адресом."
          : upstream.status === 429 ? "Слишком много попыток. Подождите минуту и повторите вход."
          : upstream.status === 403 ? "Сервер отклонил вход (403). Проверьте CORS_ALLOW_ORIGINS и PUBLIC_APP_URL в .env."
          : upstream.status === 422 ? "Проверьте формат логина и пароля."
          : `Сервис входа ответил ошибкой ${upstream.status}. Повторите попытку.`,
      );
      const retry = upstream.headers.get("retry-after");
      if (retry) response.headers.set("Retry-After", retry);
      return response;
    }
    const data = await upstream.json();
    if (typeof data.access_token !== "string" || !data.access_token || typeof data.refresh_token !== "string" || !data.refresh_token) {
      return error(502, "upstream_error", "Сервис входа вернул неполный ответ. Повторите попытку.");
    }
    const response = NextResponse.json({ ok: true }, { headers: { "Cache-Control": "private, no-store" } });
    setAccessCookie(response, data.access_token, { upstreamExpiresIn: data.expires_in, request: req });
    setRefreshCookie(response, data.refresh_token, { refreshExpiresIn: data.refresh_expires_in, request: req });
    return response;
  } catch {
    return error(503, "upstream_unavailable", "Сервис входа временно недоступен. Повторите попытку.");
  } finally { clearTimeout(timer); }
}
