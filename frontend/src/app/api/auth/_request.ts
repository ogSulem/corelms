// Browser-origin checks belong at the cookie-bearing BFF as well as the API.
// Missing Origin is allowed for non-browser clients; cross-site browser POSTs
// and opaque ("null") origins are not. Never trust x-forwarded-host from a caller.

/**
 * Заголовки HTTP — байты. Клиент, отправивший Origin в UTF-8 «как есть»,
 * доезжает до Node как latin1-искажение (`ÐºÐ°Ñ€ÐºÐ°ÑÑ‚Ð°Ð¹Ð³Ð¸`), и сравнение
 * строк падает. Здесь возвращаем исходный UTF-8, если это возможно.
 */
function repairUtf8Header(value: string): string {
  if (!value) return value;
  let latin1Only = true;
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code > 0xff) return value; // уже настоящая кириллица — не трогаем
    if (code >= 0x80) latin1Only = false;
  }
  if (latin1Only) return value;
  let out = "";
  for (let i = 0; i < value.length; ) {
    const b = value.charCodeAt(i);
    if (b < 0x80) { out += String.fromCharCode(b); i += 1; continue; }
    const b1 = value.charCodeAt(i + 1);
    const b2 = value.charCodeAt(i + 2);
    if (b >= 0xc2 && b <= 0xdf && (b1 & 0xc0) === 0x80) {
      out += String.fromCharCode(((b & 0x1f) << 6) | (b1 & 0x3f));
      i += 2;
      continue;
    }
    if (b >= 0xe0 && b <= 0xef && (b1 & 0xc0) === 0x80 && (b2 & 0xc0) === 0x80) {
      out += String.fromCharCode(((b & 0x0f) << 12) | ((b1 & 0x3f) << 6) | (b2 & 0x3f));
      i += 3;
      continue;
    }
    return value; // не UTF-8 — оставляем как пришло
  }
  return out;
}

/**
 * Origin в ASCII-форме.
 *
 * `new URL('https://edu.каркастайги.рф').origin` даёт punycode, поэтому
 * кириллический Origin (его присылают некоторые WebView и старые клиенты)
 * нужно нормализовать, а не отбрасывать. Раньше такой запрос получал 403
 * «Недопустимый источник»: страница открывалась, а вход не работал.
 * Возвращаем null, если это не голый http(s)-origin (путь, query, "null").
 */
export function asciiOrigin(value: string | null | undefined): string | null {
  const raw = repairUtf8Header(String(value || "").trim());
  if (!/^https?:\/\/[^/?#]+$/i.test(raw)) return null;
  try {
    const url = new URL(raw);
    if (!["http:", "https:"].includes(url.protocol)) return null;
    return url.origin;
  } catch {
    return null;
  }
}

export function allowedAuthRequest(request: Request): boolean {
  if (request.headers.get("sec-fetch-site") === "cross-site") return false;
  const origin = request.headers.get("origin");
  if (!origin) return true;
  const normalized = asciiOrigin(origin);
  if (!normalized) return false;

  const allowed = new Set<string>();
  try {
    allowed.add(new URL(request.url).origin);
  } catch {
    // некорректный URL запроса — проверяем только явные источники ниже
  }
  const host = request.headers.get("host");
  const protocol = String(request.headers.get("x-forwarded-proto") || "").split(",")[0].trim().toLowerCase();
  let requestScheme = "";
  try {
    requestScheme = new URL(request.url).protocol.replace(":", "");
  } catch {
    // некорректный URL запроса — схему определим по x-forwarded-proto
  }
  const secure = protocol === "https" || requestScheme === "https";
  if (host) {
    // Если запрос пришёл по HTTPS, http://host не считаем своим: иначе
    // понижение схемы на прокси позволило бы выставить куки со стороны.
    for (const scheme of secure ? ["https"] : ["http", "https"]) allowed.add(`${scheme}://${host}`);
  }
  for (const value of [process.env.PUBLIC_APP_URL, ...(process.env.CORS_ALLOW_ORIGINS || "").split(",")]) {
    const candidate = asciiOrigin(value);
    if (candidate) allowed.add(candidate);
  }
  return allowed.has(normalized);
}

export function authHeaders(request: Request, initial?: HeadersInit): Headers {
  const headers = new Headers(initial);
  for (const name of ["x-real-ip", "x-forwarded-for", "forwarded", "user-agent", "origin"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // Наверх уходит только ASCII-форма: backend сравнивает Origin строками.
  const origin = request.headers.get("origin");
  const normalized = asciiOrigin(origin);
  if (normalized) headers.set("origin", normalized);
  return headers;
}

/** Невидимые символы из буфера обмена и автозаполнения: «operator\u200b» ≠ «operator». */
function cleanLogin(value: string): string {
  return value.replace(/[\u200B-\u200D\uFEFF]/g, "").trim();
}

export function passwordTooLong(password: unknown): boolean {
  return typeof password === "string" && new TextEncoder().encode(password).length > 72;
}

export function loginPayload(body: unknown): { username: string; password: string } | null {
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  const value = body as Record<string, unknown>;
  const raw = value.email ?? value.name;
  if (typeof raw !== "string" || typeof value.password !== "string") return null;
  const username = cleanLogin(raw);
  if (!username || username.length > 320 || !value.password || passwordTooLong(value.password)) return null;
  return { username, password: value.password };
}
