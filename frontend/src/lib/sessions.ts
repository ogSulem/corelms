/**
 * Устройства и сессии в личном кабинете.
 *
 * Каждый вход — отдельная сессия, поэтому телефон, с которого заходили трижды,
 * даёт три одинаковые на вид строки. Показываем их одной карточкой устройства
 * со списком входов: видно, что это не «дубли», и можно закрыть лишние разом.
 */

export type SessionItemLike = {
  session_id: string;
  created_at?: string | null;
  last_used_at?: string | null;
  expires_at?: string | null;
  ip?: string | null;
  user_agent?: string | null;
  current?: boolean;
};

export type SessionGroup<T extends SessionItemLike> = {
  key: string;
  device: string;
  ip: string;
  sessions: T[];
  current: boolean;
};

/** «iPhone · Safari» из User-Agent; пустая строка — если браузер не представился. */
export function deviceLabelFromUa(ua: string | null | undefined): string {
  const s = String(ua || "").trim();
  if (!s) return "Неизвестное устройство";
  const low = s.toLowerCase();
  // Порядок важен: Android содержит «linux», iPad в новых прошивках — «macintosh».
  let os = "";
  if (low.includes("iphone") || low.includes("ipad") || low.includes("ipod") || low.includes("ios")) os = "iOS";
  else if (low.includes("android")) os = "Android";
  else if (low.includes("windows")) os = "Windows";
  else if (low.includes("mac os x") || low.includes("macintosh")) os = "macOS";
  else if (low.includes("linux")) os = "Linux";
  let br = "";
  if (low.includes("edg/")) br = "Edge";
  else if (low.includes("opr/") || low.includes("opera")) br = "Opera";
  else if (low.includes("yabrowser")) br = "Яндекс.Браузер";
  else if (low.includes("firefox/")) br = "Firefox";
  else if (low.includes("chrome/") && !low.includes("chromium")) br = "Chrome";
  else if (low.includes("safari/")) br = "Safari";
  const out = [os, br].filter(Boolean).join(" · ");
  return out || "Неизвестное устройство";
}

function stamp(value: string | null | undefined): number {
  const raw = String(value || "").trim();
  if (!raw) return 0;
  const parsed = Date.parse(raw);
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 * Группирует сессии по устройству и адресу. Внутри группы — свежие сверху.
 * Группа с текущей сессией всегда первая: с неё начинается разговор.
 */
export function groupSessions<T extends SessionItemLike>(items: T[]): SessionGroup<T>[] {
  const groups = new Map<string, SessionGroup<T>>();
  for (const item of items) {
    const device = deviceLabelFromUa(item.user_agent);
    const ip = String(item.ip || "").trim();
    const key = `${device}|${ip}`;
    let group = groups.get(key);
    if (!group) {
      group = { key, device, ip, sessions: [], current: false };
      groups.set(key, group);
    }
    group.sessions.push(item);
    if (item.current) group.current = true;
  }
  const list = [...groups.values()];
  for (const group of list) {
    group.sessions.sort((a, b) => stamp(b.last_used_at) - stamp(a.last_used_at));
  }
  list.sort((a, b) => {
    if (a.current !== b.current) return a.current ? -1 : 1;
    return stamp(b.sessions[0]?.last_used_at) - stamp(a.sessions[0]?.last_used_at);
  });
  return list;
}

/** Дата и время по-русски; пустая строка — если значения нет. */
export function formatSessionTime(value: string | null | undefined): string {
  const ms = stamp(value);
  if (!ms) return "";
  return new Date(ms).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
