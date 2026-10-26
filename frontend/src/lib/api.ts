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

const DEFAULT_API_TIMEOUT_MS = 25_000;

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

let refreshInFlight: Promise<boolean> | null = null;

export async function refreshSession(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch("/api/auth/refresh", { method: "POST", cache: "no-store", credentials: "include", signal: controller.signal });
      if (response.ok) return true;
      if (response.status === 401 || response.status === 403) return false;
      throw new CoreApiError("Не удалось обновить сессию из-за временной ошибки сервера. Повторите действие.", { status: response.status, errorCode: "auth_temporarily_unavailable" });
    } catch (error) {
      if (error instanceof CoreApiError) throw error;
      throw new CoreApiError("Нет связи с сервером авторизации. Повторите действие, когда соединение восстановится.", { status: 503, errorCode: "auth_temporarily_unavailable" });
    } finally { clearTimeout(timer); refreshInFlight = null; }
  })();
  return refreshInFlight;
}

function _redirectToLogin(): void {
  if (typeof window === "undefined") return;
  window.location.href = "/";
}

export async function apiFetch<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
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

  const timeoutMs = typeof init?.timeoutMs === "number" && Number.isFinite(init.timeoutMs) ? Math.max(1, init.timeoutMs) : DEFAULT_API_TIMEOUT_MS;
  const doFetch = async (): Promise<Response> => {
    const controller = new AbortController();
    const abort = () => controller.abort();
    const timer = setTimeout(abort, timeoutMs);
    init?.signal?.addEventListener("abort", abort, { once: true });
    if (init?.signal?.aborted) controller.abort();
    try {
      return await fetch(url, { ...init, headers, credentials: "include", cache: "no-store", signal: controller.signal });
    } catch (error) {
      if (init?.signal?.aborted) throw error;
      if ((error as Error)?.name === "AbortError") throw new CoreApiError("Превышено время ожидания ответа сервера. Повторите попытку.", { status: 408, errorCode: "client_timeout", requestId: headers.get("X-Request-ID") || undefined });
      throw new CoreApiError("Соединение с сервером прервано. Повторите попытку.", { status: 503, errorCode: "network_error" });
    } finally { clearTimeout(timer); init?.signal?.removeEventListener("abort", abort); }
  };
  let res = await doFetch();
  if (res.status === 401 && typeof window !== "undefined") {
    const isAuthEndpoint = ["auth/token", "auth/refresh", "auth/logout", "auth/register", "auth/reset-password/confirm"].includes(clean);
    if (!isAuthEndpoint && await refreshSession()) res = await doFetch();
    if (res.status === 401) _redirectToLogin();
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
          else if (Array.isArray(detail)) msg = detail.map(item => typeof item === "object" && item ? `${(item.loc || []).join(" → ")}: ${item.msg || "Некорректное значение"}` : String(item)).join("\n");
          else if (detail && typeof detail === "object") {
            const d: any = detail as any;
            const code = String(d?.error_code || "");
            const hint = String(d?.error_hint || "");
            const emsg = String(d?.error_message || d?.message || "");
            if (!errorCode && code) errorCode = code;
            msg = [emsg, hint].filter(Boolean).join("\n");
          }
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

    const rawLower = raw.toLowerCase();
    if (res.status >= 500) {
      const friendly = "Ошибка сервера. Повторите попытку позже.";
      const isGeneric = !raw || rawLower === "internal server error" || rawLower.includes("internal server error");
      throw new CoreApiError(isGeneric ? friendly : raw, {
        status: res.status,
        errorCode: errorCode || undefined,
        requestId: requestId || undefined,
      });
    }
    if (res.status === 429) {
      throw new CoreApiError("Слишком много запросов. Подождите немного и повторите.", {
        status: res.status,
        errorCode: errorCode || "rate_limited",
        requestId: requestId || undefined,
      });
    }
    if (res.status === 403 && (errorCode === "confirm_reading_required" || raw.includes("confirm reading"))) {
      throw new CoreApiError("Сначала подтвердите прочтение теории, затем начните тест.", {
        status: res.status,
        errorCode: errorCode || "confirm_reading_required",
        requestId: requestId || undefined,
      });
    }
    if (res.status === 409 && (errorCode === "time_limit_exceeded" || raw.includes("time limit"))) {
      throw new CoreApiError("Время на тест истекло. Начните тест заново.", {
        status: res.status,
        errorCode: errorCode || "time_limit_exceeded",
        requestId: requestId || undefined,
      });
    }
    if (res.status === 409 && (errorCode === "session_expired" || raw.includes("expired"))) {
      throw new CoreApiError("Сессия теста истекла. Начните тест заново.", {
        status: res.status,
        errorCode: errorCode || "session_expired",
        requestId: requestId || undefined,
      });
    }

    if (requestId && typeof console !== "undefined" && process.env.NODE_ENV !== "production") {
      console.error(`[corelms] api error request_id=${requestId} status=${res.status} code=${errorCode || ""} path=${clean}`);
    }

    throw new CoreApiError(raw || `HTTP ${res.status}`, {
      status: res.status,
      errorCode: errorCode || undefined,
      requestId: requestId || undefined,
    });
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
