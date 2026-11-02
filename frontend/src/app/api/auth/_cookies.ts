import { domainToASCII } from "url";

import { appendSetCookie, expiredCookie, serializeCookie } from "./_jar";

/** Любой ответ, куда можно дописать заголовок Set-Cookie (NextResponse или Response). */
type CookieTarget = { headers: Headers };

function _isProd(): boolean {
  return process.env.NODE_ENV === "production";
}

/**
 * Защищено ли соединение на самом деле. За nginx/Caddy смотрим X-Forwarded-Proto,
 * иначе — на протокол самого запроса.
 */
export function requestIsHttps(request?: Request | null): boolean {
  if (!request) return false;
  const forwarded = String(request.headers.get("x-forwarded-proto") || "").split(",")[0].trim().toLowerCase();
  if (forwarded === "https") return true;
  if (forwarded === "http") return false;
  try {
    return new URL(request.url).protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * Флаг Secure только для HTTPS.
 *
 * Раньше он включался по NODE_ENV=production, поэтому на `http://IP:8888`
 * браузер молча выбрасывал куку: вход «проходил», а следующий же запрос
 * получал 401 — пользователя возвращало на страницу входа. На десктопе это
 * было незаметно, если он открывал https-домен, а мобильный заходил по IP.
 * Cookie без Secure на HTTP работает, а на HTTPS Secure выставляется как надо.
 */
export function cookieSecure(request?: Request | null): boolean {
  const raw = String(process.env.COOKIE_SECURE || "").trim();
  const enforced = raw ? raw.toLowerCase() === "true" : _isProd();
  if (!enforced) return false;
  // Без контекста запроса (внутренние вызовы, тесты) доверяем настройке.
  if (!request) return true;
  return requestIsHttps(request);
}

/**
 * Кука должна получать ASCII-домен: браузер хранит только punycode.
 * Кириллический COOKIE_DOMAIN (edu.каркастайги.рф) раньше молча отбрасывался,
 * из-за чего кука становилась host-only без всякого предупреждения.
 */
export function normalizeCookieDomain(raw: string | null | undefined): string | undefined {
  const value = String(raw || "").trim().replace(/^\./, "").replace(/\.$/, "");
  if (!value) return undefined;
  if (/^[\x00-\x7F]+$/.test(value)) return value.toLowerCase();
  const ascii = domainToASCII(value);
  return ascii ? ascii.toLowerCase() : undefined;
}

/** Хост, к которому обратился браузер: punycode, без порта. */
export function requestHost(request?: Request | null): string {
  if (!request) return "";
  let raw = "";
  try {
    raw = request.headers.get("x-forwarded-host") || request.headers.get("host") || "";
  } catch {
    raw = "";
  }
  if (!raw) {
    try {
      raw = new URL(request.url).host;
    } catch {
      raw = "";
    }
  }
  const value = String(raw || "").split(",")[0].trim().replace(/^\[|\]$/g, "");
  const host = value.replace(/:\d+$/, "").toLowerCase();
  if (!host) return "";
  if (/^[\x00-\x7F]+$/.test(host)) return host;
  return (domainToASCII(host) || host).toLowerCase();
}

/**
 * Домен для Set-Cookie с учётом фактического хоста запроса.
 *
 * Браузер молча выбрасывает куку, чей `Domain` не совпадает с адресом страницы.
 * Так выглядел «мобильный не заходит»: COOKIE_DOMAIN указывал на домен, телефон
 * открывал сайт по IP — вход проходил, а сессии не было. Поэтому настроенный
 * домен применяется только к своему хосту и его поддоменам, иначе кука ставится
 * host-only, и вход работает с любого адреса.
 */
export function cookieDomainFor(request?: Request | null): string | undefined {
  const configured = normalizeCookieDomain(process.env.COOKIE_DOMAIN);
  if (!configured) return undefined;
  const host = requestHost(request);
  if (!host) return configured;
  if (host === configured || host.endsWith(`.${configured}`)) return configured;
  return undefined;
}

/**
 * Когда включён COOKIE_DOMAIN, у пользователей ещё может лежать старая
 * host-only кука с тем же именем: браузер пришлёт обе, и сервер может
 * прочитать устаревшую. Гасим host-only копию при каждой записи — отдельным
 * заголовком, потому что `response.cookies.set()` хранит куки в Map по имени
 * и вторую запись с тем же именем затирает (удаление пропадало молча).
 */
export function expireHostOnlyCookie(out: CookieTarget, name: string): void {
  appendSetCookie(out, expiredCookie(name, { httpOnly: true, sameSite: "lax" }));
}

function tokenConfiguredMaxAgeSeconds(): number {
  const v = Number.parseInt(process.env.CORE_TOKEN_MAX_AGE_SECONDS || "3600", 10);
  return Number.isFinite(v) && v > 0 ? v : 3600;
}

function effectiveAccessMaxAgeSeconds(upstreamExpiresIn?: number | null): number {
  const configured = tokenConfiguredMaxAgeSeconds();
  const u = typeof upstreamExpiresIn === "number" && Number.isFinite(upstreamExpiresIn) && upstreamExpiresIn > 0 ? upstreamExpiresIn : null;
  return u ? Math.min(configured, u) : configured;
}

export function setAccessCookie(out: CookieTarget, accessToken: string, opts?: { upstreamExpiresIn?: number | null; request?: Request | null }): void {
  const value = String(accessToken || "").trim();
  if (!value) return;
  const maxAge = effectiveAccessMaxAgeSeconds(opts?.upstreamExpiresIn ?? null);
  const domain = cookieDomainFor(opts?.request);
  // Сначала гасим возможную host-only копию, затем ставим доменную.
  if (domain) expireHostOnlyCookie(out, "core_token");
  appendSetCookie(out, serializeCookie("core_token", value, {
    path: "/",
    domain,
    maxAge,
    expires: new Date(Date.now() + maxAge * 1000),
    httpOnly: true,
    sameSite: "lax",
    secure: cookieSecure(opts?.request),
    priority: "high",
  }));
}

export function setRefreshCookie(out: CookieTarget, refreshToken: string, opts?: { refreshExpiresIn?: number | null; request?: Request | null }): void {
  const v = String(refreshToken || "").trim();
  if (!v) return;
  const ttl =
    typeof opts?.refreshExpiresIn === "number" && Number.isFinite(opts.refreshExpiresIn) && opts.refreshExpiresIn > 0
      ? opts.refreshExpiresIn
      : 30 * 24 * 60 * 60;
  const domain = cookieDomainFor(opts?.request);
  if (domain) expireHostOnlyCookie(out, "core_refresh");
  appendSetCookie(out, serializeCookie("core_refresh", v, {
    path: "/",
    domain,
    maxAge: ttl,
    expires: new Date(Date.now() + ttl * 1000),
    httpOnly: true,
    sameSite: "lax",
    secure: cookieSecure(opts?.request),
    priority: "high",
  }));
}

export function clearAuthCookies(out: CookieTarget, request?: Request | null): void {
  const domain = cookieDomainFor(request);
  const secure = cookieSecure(request);
  // Гасим и host-only, и доменную копию: при смене COOKIE_DOMAIN у пользователя
  // остаётся старая кука, и выход «не срабатывает» — сессия живёт дальше.
  // Каждое удаление — отдельным заголовком, иначе остаётся только последнее.
  for (const name of ["core_token", "core_refresh"]) {
    appendSetCookie(out, expiredCookie(name, { secure, httpOnly: true, sameSite: "lax" }));
    if (domain) {
      appendSetCookie(out, expiredCookie(name, { domain, secure, httpOnly: true, sameSite: "lax" }));
    }
  }
}
