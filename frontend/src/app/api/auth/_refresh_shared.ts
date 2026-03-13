type RefreshOk = {
  ok: true;
  access: string;
  nextRefresh?: string;
  expiresIn?: number | null;
  refreshExpiresIn?: number | null;
};

type RefreshFail = { ok: false; status: number };

let refreshInFlight: Promise<RefreshOk | RefreshFail> | null = null;

function _timeoutMs(): number {
  const raw = Number.parseInt(process.env.BACKEND_PROXY_TIMEOUT_MS || "25000", 10);
  // Keep it bounded: avoid accidental "0" or a huge value that would stall requests forever.
  if (!Number.isFinite(raw) || raw <= 0) return 25_000;
  return Math.min(Math.max(1_000, raw), 180_000);
}

export async function sharedRefresh(
  args: {
    apiBaseUrl: string;
    refreshToken: string;
    proxyHeaders?: { xRealIp?: string | null; xForwardedFor?: string | null; forwarded?: string | null };
  },
): Promise<RefreshOk | RefreshFail> {
  const rt = String(args.refreshToken || "").trim();
  if (!rt) return { ok: false, status: 401 };

  const run = async (): Promise<RefreshOk | RefreshFail> => {
    let res: Response;
    try {
      const headers = new Headers({ Authorization: `Bearer ${rt}` });
      const xri = args.proxyHeaders?.xRealIp;
      const xff = args.proxyHeaders?.xForwardedFor;
      const fwd = args.proxyHeaders?.forwarded;
      if (xri) headers.set("x-real-ip", xri);
      if (xff) headers.set("x-forwarded-for", xff);
      if (fwd) headers.set("forwarded", fwd);
      const ac = typeof AbortController !== "undefined" ? new AbortController() : null;
      const t = ac ? setTimeout(() => ac.abort(), _timeoutMs()) : null;
      try {
        res = await fetch(`${args.apiBaseUrl}/auth/refresh`, {
          method: "POST",
          cache: "no-store",
          headers,
          signal: ac?.signal,
        });
      } finally {
        if (t) clearTimeout(t);
      }
    } catch (e) {
      if ((e as any)?.name === "AbortError") {
        return { ok: false, status: 504 };
      }
      return { ok: false, status: 502 };
    }

    if (!res.ok) {
      return { ok: false, status: 401 };
    }

    const data = (await res.json()) as {
      access_token: string;
      refresh_token?: string | null;
      expires_in?: number | null;
      refresh_expires_in?: number | null;
    };

    const access = String(data?.access_token || "").trim();
    if (!access) return { ok: false, status: 401 };

    const nextRefresh = String(data?.refresh_token || "").trim();
    return {
      ok: true,
      access,
      nextRefresh: nextRefresh || undefined,
      expiresIn: data?.expires_in ?? null,
      refreshExpiresIn: data?.refresh_expires_in ?? null,
    };
  };

  const p = refreshInFlight || (refreshInFlight = run().finally(() => {
    refreshInFlight = null;
  }));
  return await p;
}
