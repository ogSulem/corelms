/**
 * Срок жизни access-токена без проверки подписи.
 *
 * Нужен прокси: тело большой загрузки отправляется один раз (это поток), поэтому
 * просроченный токен нельзя «переиграть» повтором после 401 — пользователь
 * загрузил бы гигабайт заново. Подпись здесь не проверяется: решение принимает
 * только backend, а нам нужно понять «обновить сессию заранее или нет».
 */
export function tokenExpiresSoon(token: string, skewSeconds = 60, nowMs = Date.now()): boolean {
  try {
    const part = String(token || "").split(".")[1];
    if (!part) return false;
    const payload = JSON.parse(Buffer.from(part, "base64url").toString("utf8")) as { exp?: unknown };
    const exp = Number(payload?.exp);
    if (!Number.isFinite(exp) || exp <= 0) return false;
    return exp * 1000 - nowMs < skewSeconds * 1000;
  } catch {
    return false;
  }
}
