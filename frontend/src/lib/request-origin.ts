/**
 * Публичный origin запроса для серверных редиректов.
 *
 * Приложение живёт за обратным прокси: браузер обращается к
 * `edu.каркастайги.рф`, а Next.js видит внутренний адрес (`http://frontend:3000`).
 * Прямой `NextResponse.redirect(req.nextUrl)` уводил пользователя на внутренний
 * хост, поэтому origin собирается из `X-Forwarded-Host` / `X-Forwarded-Proto`
 * (`Host` — запасной вариант). Клиент может подделать эти заголовки, но прокси
 * их перезаписывает, а редирект всегда ведёт только на собственный `/login`.
 */

type HeaderSource = { get(name: string): string | null };

const firstValue = (raw: string | null | undefined): string => {
  const value = String(raw || "").split(",")[0].trim();
  return value;
};

const safeProtocol = (raw: string | null | undefined): string => {
  const value = firstValue(raw).toLowerCase();
  return value === "http" || value === "https" ? value : "";
};

const safeHost = (raw: string | null | undefined): string => {
  const value = firstValue(raw);
  // Только хост[:порт]. Схема, путь, учётные данные, пробелы и управляющие
  // символы отбрасываются; кириллические домены (edu.каркастайги.рф) допустимы.
  if (!value || /[\s/\\?#@]/.test(value)) return "";
  if (!/^[\p{L}\p{N}._~:\[\]-]+$/u.test(value)) return "";
  try {
    return new URL(`http://${value}`).host;
  } catch {
    return "";
  }
};

export function requestOrigin(headers: HeaderSource, fallback: string): string {
  let fallbackProto = "https";
  let fallbackHost = "";
  try {
    const parsed = new URL(fallback);
    fallbackProto = parsed.protocol.replace(":", "") || "https";
    fallbackHost = parsed.host;
  } catch {
    // Некорректный запасной адрес — используем значения по умолчанию.
  }
  const proto = safeProtocol(headers.get("x-forwarded-proto")) || safeProtocol(headers.get("x-forwarded-protocol")) || fallbackProto;
  const host = safeHost(headers.get("x-forwarded-host")) || safeHost(headers.get("host")) || fallbackHost;
  if (!host) return fallback;
  return `${proto}://${host}`;
}

export function loginRedirectUrl(input: {
  headers: HeaderSource;
  fallbackOrigin: string;
  next: string;
}): URL {
  const url = new URL("/login", requestOrigin(input.headers, input.fallbackOrigin));
  if (input.next) url.searchParams.set("redirect", input.next);
  return url;
}
