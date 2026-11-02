/**
 * Чтение кук без потери дублей и запись Set-Cookie «как есть».
 *
 * Почему это отдельный модуль.
 *
 * 1. У части пользователей в браузере живут ДВЕ копии `core_token`/`core_refresh`:
 *    старая host-only (поставлена до настройки `COOKIE_DOMAIN`) и новая доменная.
 *    `request.cookies.get(name)` и `next/headers` возвращают только одну — как
 *    правило первую, то есть СТАРУЮ. Дальше: сервер получает просроченный токен,
 *    отвечает 401, интерфейс уводит на главную — со стороны это выглядит как
 *    «вхожу и сразу вылетает». Здесь читаются ВСЕ копии, и выбирается рабочая.
 *
 * 2. `NextResponse.cookies.set()` хранит куки в Map по имени: вторая запись с тем
 *    же именем ЗАТИРАЕТ первую. Из-за этого удаление старой host-only копии
 *    (`Max-Age=0` без Domain) молча пропадало, и дубли оставались навсегда.
 *    Поэтому куки пишутся через `headers.append("set-cookie", …)` — каждая
 *    отдельным заголовком, как требует RFC 6265.
 */

export type CookieAttrs = {
  path?: string;
  domain?: string;
  maxAge?: number;
  expires?: Date;
  httpOnly?: boolean;
  secure?: boolean;
  sameSite?: "lax" | "strict" | "none";
  priority?: "low" | "medium" | "high";
};

/** Все значения куки в порядке, в котором их прислал браузер. */
export function cookieValues(request: Request | null | undefined, name: string): string[] {
  if (!request) return [];
  let raw = "";
  try {
    raw = request.headers.get("cookie") || "";
  } catch {
    return [];
  }
  if (!raw) return [];
  const values: string[] = [];
  for (const part of raw.split(";")) {
    const item = part.trim();
    if (!item) continue;
    const eq = item.indexOf("=");
    if (eq <= 0) continue;
    if (item.slice(0, eq).trim() !== name) continue;
    let value = item.slice(eq + 1).trim();
    if (value.startsWith('"') && value.endsWith('"')) value = value.slice(1, -1);
    try {
      value = decodeURIComponent(value);
    } catch {
      // значение не URL-кодировано — оставляем как есть
    }
    if (value) values.push(value);
  }
  return values;
}

/** Сколько копий куки пришло: >1 — в браузере остались старые куки. */
export function cookieCopyCount(request: Request | null | undefined, name: string): number {
  return cookieValues(request, name).length;
}

function jwtExpiry(token: string): number {
  try {
    const payload = token.split(".")[1];
    if (!payload) return 0;
    const json = JSON.parse(Buffer.from(payload.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8"));
    const exp = Number(json?.exp);
    return Number.isFinite(exp) ? exp : 0;
  } catch {
    return 0;
  }
}

/**
 * Токены доступа от самого «свежего» к самому старому.
 *
 * Подпись здесь не проверяется (секрета на фронтенде нет) — порядок нужен
 * только для перебора: backend всё равно отклонит негодный токен. Сравниваем
 * по `exp`, без него — по порядку в заголовке (сначала новые).
 */
export function accessTokens(request: Request | null | undefined): string[] {
  const values = cookieValues(request, "core_token");
  if (values.length < 2) return values;
  return values
    .map((value, index) => ({ value, index, exp: jwtExpiry(value) }))
    .sort((a, b) => (b.exp - a.exp) || (b.index - a.index))
    .map((item) => item.value);
}

/**
 * Refresh-токены: сначала последний присланный (браузер отдаёт более старые
 * куки первыми), затем остальные — если сервер отверг первый, пробуем
 * следующий, а не выкидываем пользователя.
 */
export function refreshTokens(request: Request | null | undefined): string[] {
  const values = cookieValues(request, "core_refresh");
  return values.length > 1 ? [...values].reverse() : values;
}

const COOKIE_DATE_EPOCH = "Thu, 01 Jan 1970 00:00:00 GMT";

export function serializeCookie(name: string, value: string, attrs: CookieAttrs = {}): string {
  const parts = [`${name}=${value}`];
  parts.push(`Path=${attrs.path || "/"}`);
  if (attrs.domain) parts.push(`Domain=${attrs.domain}`);
  if (typeof attrs.maxAge === "number") parts.push(`Max-Age=${Math.trunc(attrs.maxAge)}`);
  if (attrs.expires) parts.push(`Expires=${attrs.expires.toUTCString()}`);
  if (attrs.secure) parts.push("Secure");
  if (attrs.httpOnly) parts.push("HttpOnly");
  if (attrs.sameSite) parts.push(`SameSite=${attrs.sameSite === "none" ? "None" : attrs.sameSite === "strict" ? "Strict" : "Lax"}`);
  if (attrs.priority) parts.push(`Priority=${attrs.priority}`);
  return parts.join("; ");
}

/** Удаление куки для конкретной области (host-only или доменной). */
export function expiredCookie(name: string, opts: { domain?: string; secure?: boolean; httpOnly?: boolean; sameSite?: CookieAttrs["sameSite"] } = {}): string {
  return serializeCookie(name, "", {
    path: "/",
    domain: opts.domain,
    maxAge: 0,
    expires: new Date(COOKIE_DATE_EPOCH),
    secure: opts.secure,
    httpOnly: opts.httpOnly,
    sameSite: opts.sameSite,
  });
}

type Headered = { headers: { append: (name: string, value: string) => void } };

/** Дописать заголовок Set-Cookie, не затирая уже добавленные. */
export function appendSetCookie(out: Headered, cookie: string): void {
  out.headers.append("set-cookie", cookie);
}
