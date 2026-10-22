// Browser-origin checks belong at the cookie-bearing BFF as well as the API.
// Missing Origin is allowed for non-browser clients; cross-site browser POSTs
// and opaque ("null") origins are not. Never trust x-forwarded-host from a caller.
export function allowedAuthRequest(request: Request): boolean {
  if (request.headers.get("sec-fetch-site") === "cross-site") return false;
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try {
    const parsed = new URL(origin);
    if (!["http:", "https:"].includes(parsed.protocol) || parsed.origin !== origin) return false;
    const incoming = new URL(request.url);
    const allowed = new Set([incoming.origin]);
    const host = request.headers.get("host");
    const protocol = request.headers.get("x-forwarded-proto") || incoming.protocol.replace(":", "");
    if (host && ["http", "https"].includes(protocol)) allowed.add(`${protocol}://${host}`);
    for (const value of [process.env.PUBLIC_APP_URL, ...(process.env.CORS_ALLOW_ORIGINS || "").split(",")]) {
      if (value?.trim()) {
        try { allowed.add(new URL(value.trim()).origin); } catch { /* invalid deployment entry */ }
      }
    }
    return allowed.has(origin);
  } catch { return false; }
}

export function authHeaders(request: Request, initial?: HeadersInit): Headers {
  const headers = new Headers(initial);
  for (const name of ["x-real-ip", "x-forwarded-for", "forwarded", "user-agent", "origin"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  return headers;
}

export function loginPayload(body: unknown): { username: string; password: string } | null {
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  const value = body as Record<string, unknown>;
  const username = value.email ?? value.name;
  if (typeof username !== "string" || typeof value.password !== "string") return null;
  if (!username.trim() || username.length > 320 || !value.password || new TextEncoder().encode(value.password).length > 72) return null;
  return { username: username.trim(), password: value.password };
}
