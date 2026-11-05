import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { loginRedirectUrl } from "@/lib/request-origin";

/**
 * Серверная проверка сессии для закрытых разделов.
 *
 * Файл лежал в `frontend/middleware.ts`, но при структуре `src/app` Next.js
 * читает только `src/middleware.ts` — проверка не включалась никогда, и
 * незалогиненный пользователь видел разметку кабинета до клиентского запроса.
 *
 * Правила намеренно узкие: защищаем известные разделы по префиксу, а не «всё,
 * кроме списка». Иначе запросы картинок и иконок (`/icon.png`) от гостя тоже
 * уезжали бы на форму входа, и лендинг оставался без оформления.
 */
const PROTECTED_PREFIXES = ["/dashboard", "/modules", "/submodules", "/quizzes", "/account", "/sales", "/admin", "/force-password-change"];

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  if (!PROTECTED_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))) {
    return NextResponse.next();
  }

  const token = req.cookies.get("core_token")?.value;
  const refresh = req.cookies.get("core_refresh")?.value;
  if (token || refresh) return NextResponse.next();

  // Без сессии ведём на форму входа, а не на промо-страницу: раньше мобильный
  // «заходил» и молча оказывался на лендинге без объяснения причины.
  // Origin берём из заголовков прокси: `req.nextUrl` за обратным прокси может
  // содержать внутренний адрес, и редирект уводил бы на него.
  const url = loginRedirectUrl({
    headers: req.headers,
    fallbackOrigin: req.nextUrl.origin,
    next: `${pathname}${search || ""}`,
  });
  return NextResponse.redirect(url);
}
