import { useEffect, useRef, useState } from 'react';

export type User = {
  name: string;
  role: 'admin' | 'user';
  xp: number;
  level: number;
  streak: number;
  must_change_password?: boolean;
};

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const meInFlightRef = useRef(false);
  const lastMeAtRef = useRef(0);
  const hasLoadedOnceRef = useRef(false);

  const fetchMe = async () => {
    const now = Date.now();
    if (meInFlightRef.current) return;
    if (now - lastMeAtRef.current < 3000) return;
    meInFlightRef.current = true;
    lastMeAtRef.current = now;
    try {
      if (!hasLoadedOnceRef.current) setLoading(true);
      const res = await fetch('/api/auth/me', { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        if (data.authenticated) {
          setUser(data.user);
        } else {
          setUser(null);
        }
      } else {
        setUser(null);
      }
    } catch (err) {
      setError(err as Error);
      setUser(null);
    } finally {
      hasLoadedOnceRef.current = true;
      setLoading(false);
      meInFlightRef.current = false;
    }
  };

  useEffect(() => {
    fetchMe();
  }, []);

  return { user, loading, error, refresh: fetchMe };
}
