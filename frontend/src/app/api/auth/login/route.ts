import { NextResponse } from "next/server";
import { setAccessCookie, setRefreshCookie } from "../_cookies";
import { allowedAuthRequest, authHeaders, loginPayload } from "../_request";

const API_BASE_URL = process.env.CORE_INTERNAL_API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://backend:8000";
const error = (status: number, error_code: string, error_message: string) =>
  NextResponse.json({ ok: false, error_code, error_message }, { status, headers: { "Cache-Control": "private, no-store" } });

export async function POST(req: Request) {
  if (!allowedAuthRequest(req)) return error(403, "invalid_origin", "Недопустимый источник запроса");
  let payload;
  try { payload = loginPayload(await req.json()); }
  catch { return error(400, "invalid_payload", "Проверьте логин и пароль"); }
  if (!payload) return error(400, "invalid_payload", "Проверьте логин и пароль");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 25000);
  try {
    const upstream = await fetch(`${API_BASE_URL}/auth/token`, {
      method: "POST", body: new URLSearchParams(payload), cache: "no-store", signal: controller.signal,
      headers: authHeaders(req, { "Content-Type": "application/x-www-form-urlencoded" }),
    });
    if (!upstream.ok) {
      const response = error(upstream.status, upstream.status === 401 ? "invalid_credentials" : "upstream_error",
        upstream.status === 401 ? "Неверный логин или пароль" : upstream.status === 429 ? "Слишком много попыток. Подождите и повторите вход." : "Не удалось войти. Повторите попытку.");
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
