import { createHash } from "node:crypto";

type RefreshOk = { ok: true; access: string; nextRefresh?: string; expiresIn?: number | null; refreshExpiresIn?: number | null };
type RefreshFail = { ok: false; status: number };
type RefreshResult = RefreshOk | RefreshFail;

// This is SERVER state. A single global promise would send one user's tokens to
// another user refreshing concurrently. Isolate by credential AND upstream.
const refreshes = new Map<string, { promise: Promise<RefreshResult>; expiresAt: number }>();

function timeoutMs(): number {
  const raw = Number.parseInt(process.env.BACKEND_PROXY_TIMEOUT_MS || "25000", 10);
  return Number.isFinite(raw) && raw > 0 ? Math.min(Math.max(1000, raw), 180000) : 25000;
}

export async function sharedRefresh(args: {
  apiBaseUrl: string;
  refreshToken: string;
  proxyHeaders?: { xRealIp?: string | null; xForwardedFor?: string | null; forwarded?: string | null; userAgent?: string | null; origin?: string | null };
}): Promise<RefreshResult> {
  const token = String(args.refreshToken || "").trim();
  if (!token) return { ok: false, status: 401 };
  const now = Date.now();
  for (const [key, entry] of refreshes) if (entry.expiresAt <= now) refreshes.delete(key);
  const key = createHash("sha256").update(`${args.apiBaseUrl}\0${token}`).digest("hex");
  const existing = refreshes.get(key);
  if (existing) return existing.promise;

  const run = async (): Promise<RefreshResult> => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs());
    try {
      const headers = new Headers({ Authorization: `Bearer ${token}` });
      const proxy = args.proxyHeaders;
      if (proxy?.xRealIp) headers.set("x-real-ip", proxy.xRealIp);
      if (proxy?.xForwardedFor) headers.set("x-forwarded-for", proxy.xForwardedFor);
      if (proxy?.forwarded) headers.set("forwarded", proxy.forwarded);
      if (proxy?.userAgent) headers.set("user-agent", proxy.userAgent);
      if (proxy?.origin) headers.set("origin", proxy.origin);
      const response = await fetch(`${args.apiBaseUrl}/auth/refresh`, { method: "POST", cache: "no-store", headers, signal: controller.signal });
      // An upstream outage or rate limit must not invalidate an otherwise usable session.
      if (!response.ok) return { ok: false, status: response.status };
      const data = await response.json();
      const access = String(data?.access_token || "").trim();
      if (!access) return { ok: false, status: 502 };
      return { ok: true, access, nextRefresh: String(data.refresh_token || "").trim() || undefined,
        expiresIn: data.expires_in ?? null, refreshExpiresIn: data.refresh_expires_in ?? null };
    } catch (error) { return { ok: false, status: (error as Error)?.name === "AbortError" ? 504 : 502 }; }
    finally { clearTimeout(timer); }
  };

  const promise = run();
  // Bound in-flight state. Cross-worker races are handled atomically by the API.
  if (refreshes.size >= 1000) refreshes.delete(refreshes.keys().next().value!);
  const entry = { promise, expiresAt: now + timeoutMs() + 1000 };
  refreshes.set(key, entry);
  void promise.then(() => {
    // Never reuse a completed access-token response: it may already have been
    // invalidated by a password change or session revocation in another worker.
    if (refreshes.get(key) === entry) refreshes.delete(key);
  });
  return promise;
}
