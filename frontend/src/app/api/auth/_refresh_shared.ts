type RefreshOk = {
  ok: true;
  access: string;
  nextRefresh?: string;
  expiresIn?: number | null;
  refreshExpiresIn?: number | null;
};

type RefreshFail = { ok: false; status: number };

let refreshInFlight: Promise<RefreshOk | RefreshFail> | null = null;

export async function sharedRefresh(
  args: {
    apiBaseUrl: string;
    refreshToken: string;
  },
): Promise<RefreshOk | RefreshFail> {
  const rt = String(args.refreshToken || "").trim();
  if (!rt) return { ok: false, status: 401 };

  const run = async (): Promise<RefreshOk | RefreshFail> => {
    let res: Response;
    try {
      res = await fetch(`${args.apiBaseUrl}/auth/refresh`, {
        method: "POST",
        cache: "no-store",
        headers: { Authorization: `Bearer ${rt}` },
      });
    } catch {
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
