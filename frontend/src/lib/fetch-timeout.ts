/**
 * Безопасный таймаут для fetch.
 *
 * `AbortSignal.timeout()` появился в Safari 16 (iOS 16). На iPhone с iOS 15 и
 * в старых WebView его нет — вызов бросает TypeError, и действие (например,
 * «Выйти») молча не выполняется. Здесь тот же AbortController, что и везде.
 */
export function timeoutSignal(ms: number): AbortSignal {
  const controller = new AbortController();
  // Таймер, сработавший после завершения запроса, ничего не ломает: abort()
  // на уже закрытом запросе — no-op.
  setTimeout(() => controller.abort(), Math.max(1000, ms));
  return controller.signal;
}
