/**
 * Обновление списков по возврату на вкладку.
 *
 * `window.addEventListener("focus")` срабатывает и при переключении вкладок, и
 * при клике по адресной строке, и при возврате из другого окна. Раньше каждый
 * такой возврат запускал полную перезагрузку списка: таблица мигала, а сервер
 * получал запросы, которые ничего не меняли. Теперь не чаще раза в минуту, а
 * первый возврат после открытия страницы срабатывает всегда.
 */
export function throttleRefresh(run: () => void, intervalMs = 60_000, now: () => number = () => Date.now()): () => void {
  let last: number | null = null;
  return () => {
    const current = now();
    if (last !== null && current - last < intervalMs) return;
    last = current;
    run();
  };
}

/** Явное действие пользователя («Обновить») всегда работает без ограничений. */
export function alwaysAllowed(run: () => void): () => void {
  return () => run();
}
