import { useEffect, useState } from 'react';

type User = {
  id: string;
  name: string;
  role: 'admin' | 'superadmin' | 'employee';
  xp: number;
  level: number;
  streak: number;
  must_change_password?: boolean;
};

type AuthSnapshot = {
  user: User | null;
  loading: boolean;
  error: Error | null;
};

let authSnapshot: AuthSnapshot = {
  user: null,
  loading: true,
  error: null,
};

const authSubscribers = new Set<(s: AuthSnapshot) => void>();

let meInFlight = false;
let lastMeAt = 0;
let hasLoadedOnce = false;

let retryTimer: any = null;

function emitAuth() {
  for (const cb of Array.from(authSubscribers)) {
    try {
      cb(authSnapshot);
    } catch {
      // ignore
    }
  }
}

/**
 * Телефон сворачивает вкладку, и после возврата старый снимок сессии может
 * быть просрочен. Проверяем состояние при возврате на страницу, но не чаще
 * раза в 30 секунд, чтобы не плодить запросы.
 */
let visibilityWatched = false;

function watchVisibility() {
  if (visibilityWatched) return;
  if (typeof document === "undefined" || typeof document.addEventListener !== "function") return;
  visibilityWatched = true;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    if (Date.now() - lastMeAt < 30_000) return;
    void sharedFetchMe(true);
  });
}

async function sharedFetchMe(force: boolean = false) {
  const now = Date.now();
  if (meInFlight) return;
  const minIntervalMs = hasLoadedOnce ? 10_000 : 3000;
  if (!force && now - lastMeAt < minIntervalMs) return;
  meInFlight = true;
  lastMeAt = now;
  try {
    if (!hasLoadedOnce) {
      authSnapshot = { ...authSnapshot, loading: true };
      emitAuth();
    }
    const res = await fetch('/api/auth/me', { cache: 'no-store' });
    if (res.ok) {
      const data = await res.json();
      if (data.authenticated) {
        authSnapshot = { user: data.user as User, loading: false, error: null };
      } else {
        authSnapshot = { user: null, loading: false, error: null };
      }
    } else {
      authSnapshot = { ...authSnapshot, loading: false, error: new Error(`auth_me_http_${res.status}`) };
    }
  } catch (err) {
    authSnapshot = { ...authSnapshot, loading: false, error: err as Error };
  } finally {
    hasLoadedOnce = true;
    meInFlight = false;
    emitAuth();

    if (authSnapshot.error) {
      try {
        if (retryTimer) clearTimeout(retryTimer);
      } catch {
        // ignore
      }
      retryTimer = setTimeout(() => {
        retryTimer = null;
        void sharedFetchMe(true);
      }, 3000);
    }
  }
}

export function useAuth() {
  useEffect(() => {
    watchVisibility();
  }, []);

  const [user, setUser] = useState<User | null>(authSnapshot.user);
  const [loading, setLoading] = useState(authSnapshot.loading);
  const [error, setError] = useState<Error | null>(authSnapshot.error);

  useEffect(() => {
    const cb = (s: AuthSnapshot) => {
      setUser(s.user);
      setLoading(s.loading);
      setError(s.error);
    };
    authSubscribers.add(cb);
    cb(authSnapshot);
    void sharedFetchMe(false);
    return () => { authSubscribers.delete(cb); };
  }, []);

  return { user, loading, error, refresh: sharedFetchMe };
}
