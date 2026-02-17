class CoreApiError extends Error {
  status: number;
  errorCode?: string;
  requestId?: string;

  constructor(message: string, opts: { status: number; errorCode?: string; requestId?: string }) {
    super(message);
    this.name = "CoreApiError";
    this.status = opts.status;
    this.errorCode = opts.errorCode;
    this.requestId = opts.requestId;
  }
}

function _makeRequestId(): string {
  try {
    // Browser runtime
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c: any = globalThis as any;
    if (c?.crypto?.randomUUID) return String(c.crypto.randomUUID());
  } catch {
    // ignore
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const clean = path.startsWith("/") ? path.slice(1) : path;
  const url = `/api/backend/${clean}`;

  const headers = new Headers(init?.headers);
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  if (!headers.has("Content-Type") && init?.body && !isFormData) {
    headers.set("Content-Type", "application/json");
  }

  if (!headers.has("X-Request-ID")) {
    headers.set("X-Request-ID", _makeRequestId());
  }

  const timeoutMsRaw = (init as any)?.timeoutMs;
  const timeoutMs = typeof timeoutMsRaw === "number" && Number.isFinite(timeoutMsRaw) ? Math.max(1, timeoutMsRaw) : 25_000;
  const controller = !init?.signal && typeof AbortController !== "undefined" ? new AbortController() : null;
  const timeoutId = controller ? window.setTimeout(() => controller.abort(), timeoutMs) : null;

  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers,
      credentials: "include",
      cache: "no-store",
      signal: init?.signal ?? controller?.signal,
    });
  } catch (e) {
    if ((e as any)?.name === "AbortError") {
      throw new CoreApiError("Превышено время ожидания ответа сервера. Повторите попытку.", {
        status: 408,
        errorCode: "client_timeout",
        requestId: headers.get("X-Request-ID") || undefined,
      });
    }
    throw e;
  } finally {
    if (timeoutId) window.clearTimeout(timeoutId);
  }

  if (res.status === 401 && typeof window !== "undefined") {
    const next = window.location.pathname + window.location.search;
    window.location.href = `/login?next=${encodeURIComponent(next)}`;
  }

  if (!res.ok) {
    let msg = "";
    let errorCode = "";
    let requestId = "";
    const ct = res.headers.get("content-type") || "";
    try {
      if (ct.includes("application/json")) {
        const data = await res.json();
        // Standard backend error contract
        if (data && typeof data === "object" && (data.ok === false || data.ok === "false")) {
          errorCode = String((data as any).error_code || "");
          requestId = String((data as any).request_id || "");
          msg = String((data as any).error_message || "");
        }

        if (!msg) {
          const detail = (data && ((data as any).detail ?? (data as any).message)) as unknown;
          if (typeof detail === "string") msg = detail;
          else if (Array.isArray(detail)) msg = detail.map(String).join("\n");
          else if (typeof data === "string") msg = data;
        }
      } else {
        msg = await res.text();
      }
    } catch {
      try {
        msg = await res.text();
      } catch {
        msg = "";
      }
    }

    const raw = (msg || "").trim();
    if (res.status === 429) {
      throw new CoreApiError("Слишком много запросов. Подождите немного и повторите.", {
        status: res.status,
        errorCode: errorCode || "rate_limited",
        requestId: requestId || undefined,
      });
    }
    if (res.status === 403 && raw.includes("confirm reading")) {
      throw new CoreApiError("Сначала подтвердите прочтение теории, затем начните тест.", {
        status: res.status,
        errorCode: errorCode || "confirm_reading_required",
        requestId: requestId || undefined,
      });
    }
    if (res.status === 409 && raw.includes("time limit")) {
      throw new CoreApiError("Время на тест истекло. Начните тест заново.", {
        status: res.status,
        errorCode: errorCode || "time_limit_exceeded",
        requestId: requestId || undefined,
      });
    }
    if (res.status === 409 && raw.includes("expired")) {
      throw new CoreApiError("Сессия теста истекла. Начните тест заново.", {
        status: res.status,
        errorCode: errorCode || "session_expired",
        requestId: requestId || undefined,
      });
    }

    if (requestId && typeof console !== "undefined") {
      console.error(`[corelms] api error request_id=${requestId} status=${res.status} code=${errorCode || ""} path=${clean}`);
    }

    throw new CoreApiError(raw || `HTTP ${res.status}`, {
      status: res.status,
      errorCode: errorCode || undefined,
      requestId: requestId || undefined,
    });
  }

  return (await res.json()) as T;
}
