import { useEffect, useRef, useState } from 'react';

export type User = {
  name: string;
  role: 'admin' | 'user';
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

function emitAuth() {
  for (const cb of Array.from(authSubscribers)) {
    try {
      cb(authSnapshot);
    } catch {
      // ignore
    }
  }
}

async function sharedFetchMe() {
  const now = Date.now();
  if (meInFlight) return;
  if (now - lastMeAt < 3000) return;
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
      authSnapshot = { user: null, loading: false, error: null };
    }
  } catch (err) {
    authSnapshot = { user: null, loading: false, error: err as Error };
  } finally {
    hasLoadedOnce = true;
    meInFlight = false;
    emitAuth();
  }
}

export function useAuth() {
  const [user, setUser] = useState<User | null>(authSnapshot.user);
  const [loading, setLoading] = useState(authSnapshot.loading);
  const [error, setError] = useState<Error | null>(authSnapshot.error);

  const subscribedRef = useRef(false);

  useEffect(() => {
    if (!subscribedRef.current) {
      subscribedRef.current = true;
      const cb = (s: AuthSnapshot) => {
        setUser(s.user);
        setLoading(s.loading);
        setError(s.error);
      };
      authSubscribers.add(cb);
      cb(authSnapshot);
      void sharedFetchMe();
      return () => {
        authSubscribers.delete(cb);
      };
    }
    void sharedFetchMe();
  }, []);

  return { user, loading, error, refresh: sharedFetchMe };
}
