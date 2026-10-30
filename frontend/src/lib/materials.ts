import { materialDownloadUrl } from "./download-url";
import { apiFetch, refreshSession } from "@/lib/api";
import { baseName, browseMaterials, folderPath, folderSummary, splitPath } from "./folder-tree";

export { baseName, browseMaterials, folderPath, folderSummary, splitPath };

export type Material = {
  asset_id: string;
  original_filename: string;
  mime_type: string | null;
  size_bytes?: number | null;
  version?: number;
  order?: number;
  /** Готова совместимая копия (MP4/PDF) — её показываем вместо оригинала. */
  browser_copy?: boolean;
};

type MaterialKind = "table" | "document" | "text" | "pdf" | "image" | "video" | "audio" | "download";

export function fileExtension(name: string): string {
  return baseName(name).split(".").slice(1).pop()?.toLowerCase() || "";
}

/**
 * Адрес превью файла. `thumb=1` отключает запись события обучения и разрешает кэш:
 * иконки в списке не должны попадать в журнал «просмотрено».
 */
export function materialThumbUrl(assetId: string, version?: number | null, browserCopy = false): string {
  const query = new URLSearchParams({ variant: browserCopy ? "browser" : "original", thumb: "1" });
  if (version) query.set("v", String(version));
  return `/api/backend/assets/${encodeURIComponent(assetId)}/stream?${query.toString()}`;
}

export function materialKind(name: string): MaterialKind {
  const ext = fileExtension(name);
  if (["xlsx", "xlsm", "xls", "csv", "tsv"].includes(ext)) return "table";
  if (["docx", "pptx"].includes(ext)) return "document";
  if (["txt", "md", "json", "log"].includes(ext)) return "text";
  if (ext === "pdf") return "pdf";
  if (["png", "jpg", "jpeg", "webp", "gif", "avif", "bmp"].includes(ext)) return "image";
  if (["mp4", "mov", "m4v", "mkv", "avi", "webm", "wmv", "flv", "mpeg", "mpg", "mts", "m2ts", "3gp", "ogv"].includes(ext)) return "video";
  if (["mp3", "wav", "ogg", "m4a", "flac"].includes(ext)) return "audio";
  // HTML, SVG and XML are intentionally download-only on an authenticated origin.
  return "download";
}

export function formatBytes(bytes?: number | null): string {
  if (bytes == null || !Number.isFinite(bytes)) return "Размер не указан";
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} КБ`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} МБ`;
  return `${(bytes / 1024 ** 3).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ГБ`;
}

export function formatFileCount(count: number): string {
  const n = Math.abs(count) % 100;
  const word = n > 10 && n < 20 ? "файлов" : n % 10 === 1 ? "файл" : n % 10 >= 2 && n % 10 <= 4 ? "файла" : "файлов";
  return `${count} ${word}`;
}

export function columnLabel(index: number): string {
  let value = index + 1;
  let label = "";
  while (value > 0) {
    value -= 1;
    label = String.fromCharCode(65 + value % 26) + label;
    value = Math.floor(value / 26);
  }
  return label;
}

export async function downloadMaterial(assetId: string): Promise<void> {
  const { download_url } = await apiFetch<{ download_url: string }>(`/assets/${encodeURIComponent(assetId)}/presign-download?action=download`);
  const link = document.createElement("a");
  link.href = materialDownloadUrl(assetId, download_url, window.location.protocol);
  link.rel = "noopener noreferrer";
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

/**
 * Прямая загрузка в backend: nginx/Caddy проксируют /api/upload/ в backend без Next.js.
 * Next.js обрывает запрос, который принимает тело дольше ~5 минут, и большой файл
 * (видео) возвращал 502. Обратный путь /api/backend остаётся запасным для старых сборок.
 */
const UPLOAD_PATH = "/api/upload";
const FALLBACK_UPLOAD_PATH = "/api/backend";

type UploadFailure = Error & { status?: number; bodyWasJson?: boolean };

function uploadOnce<T>(base: string, path: string, form: FormData, onProgress: (percent: number) => void, signal?: AbortSignal): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${base}${path}`);
    xhr.withCredentials = true;
    xhr.timeout = 60 * 60 * 1000;
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100)); };
    const abort = () => xhr.abort();
    signal?.addEventListener("abort", abort, { once: true });
    xhr.onloadend = () => signal?.removeEventListener("abort", abort);
    xhr.onerror = () => reject(new Error("Соединение прервано во время загрузки. Файл не отправлен целиком — обновите список и повторите."));
    xhr.ontimeout = () => reject(new Error("Загрузка не завершилась за час. Проверьте соединение и повторите."));
    xhr.onabort = () => reject(new DOMException("Загрузка отменена", "AbortError"));
    xhr.onload = () => {
      let data: Record<string, unknown> | null = null;
      try { data = JSON.parse(xhr.responseText); } catch { data = null; }
      if (xhr.status >= 200 && xhr.status < 300) { resolve((data || {}) as T); return; }
      const fallback = xhr.status === 413
        ? "Файл больше разрешённого размера. Увеличьте лимит в настройках или загрузите файл меньшего размера."
        : xhr.status === 502 || xhr.status === 504
          ? "Сервер прервал загрузку. Обычно это обрыв связи на большом файле — повторите загрузку, файл не повреждён."
          : `Не удалось загрузить файл (${xhr.status})`;
      const message = String(data?.error_message || data?.detail || fallback);
      reject(Object.assign(new Error(message), { status: xhr.status, bodyWasJson: !!data }));
    };
    if (signal?.aborted) { reject(new DOMException("Загрузка отменена", "AbortError")); return; }
    xhr.send(form);
  });
}

/**
 * Большой файл режем на куски: один длинный запрос обрывают прокси и мобильные сети.
 * Каждый кусок короткий, а при обрыве повторяется только он — загрузка не начинается заново.
 */
const CHUNK_THRESHOLD_BYTES = 24 * 1024 * 1024;
const DEFAULT_CHUNK_BYTES = 8 * 1024 * 1024;
const CHUNK_RETRIES = 4;

type ChunkSession = { upload_id: string; chunk_size: number; offset: number; size_bytes: number };

function uploadError(status: number, data: Record<string, unknown> | null): Error {
  const fallback = status === 413 ? "Файл больше разрешённого размера. Лимит меняется в «Админ-центр → Настройки»."
    : status === 507 ? "На сервере не хватает места для этого файла. Освободите место и повторите загрузку."
    : status === 502 || status === 504 ? "Сервер прервал загрузку. Уже отправленные части сохранены — повторите, загрузка продолжится."
    : `Не удалось загрузить файл (${status})`;
  return Object.assign(new Error(String(data?.error_message || data?.detail || fallback)), { status, bodyWasJson: !!data });
}

async function readJson(response: Response): Promise<Record<string, unknown> | null> {
  try { return await response.json(); } catch { return null; }
}

/** Частичная загрузка: начало сессии, куски по 8 МБ, сборка. */
async function uploadChunked<T>(startUrl: string, file: File, fields: Record<string, unknown>,
                                onProgress: (percent: number) => void, signal?: AbortSignal): Promise<T> {
  const started = await fetch(startUrl, {
    method: "POST", credentials: "include", cache: "no-store", signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...fields, filename: file.name, size_bytes: file.size }),
  });
  const startData = await readJson(started);
  if (!started.ok) throw uploadError(started.status, startData);
  const session = startData as unknown as ChunkSession;
  const size = Number(session.chunk_size) || DEFAULT_CHUNK_BYTES;
  let offset = Number(session.offset) || 0;
  while (offset < file.size) {
    const end = Math.min(offset + size, file.size);
    const piece = file.slice(offset, end);
    let attempt = 0;
    for (;;) {
      try {
        const response = await fetch(`${startUrl}/${session.upload_id}?offset=${offset}`, {
          method: "PUT", credentials: "include", cache: "no-store", signal,
          headers: { "Content-Type": "application/octet-stream" },
          body: piece,
        });
        const data = await readJson(response);
        if (!response.ok) {
          // 401 — сессия истекла: одну попытку продлеваем, как и при обычной загрузке.
          if (response.status === 401 && attempt === 0 && await refreshSession()) { attempt += 1; continue; }
          throw uploadError(response.status, data);
        }
        offset = Number(data?.offset ?? end);
        onProgress(Math.min(99, Math.round(offset / file.size * 100)));
        break;
      } catch (error) {
        if (signal?.aborted) throw error;
        const status = (error as { status?: number }).status;
        if (status && status < 500 && status !== 408 && status !== 429) throw error;
        attempt += 1;
        if (attempt > CHUNK_RETRIES) throw error;
        await new Promise(resolve => setTimeout(resolve, 800 * attempt));
      }
    }
  }
  // Сборка файла на сервере может быть долгой. Повтор безопасен: сервер возвращает
  // уже сохранённый результат, а не создаёт второй файл.
  for (let attempt = 0; ; attempt += 1) {
    let finished: Response | null = null;
    try {
      finished = await fetch(`${startUrl}/${session.upload_id}/complete`, {
        method: "POST", credentials: "include", cache: "no-store", signal,
        headers: { "Content-Type": "application/json" }, body: "{}",
      });
    } catch (error) {
      if (signal?.aborted || attempt >= CHUNK_RETRIES) throw error;
      await new Promise(resolve => setTimeout(resolve, 1500 * (attempt + 1)));
      continue;
    }
    const doneData = await readJson(finished);
    if (finished.ok) { onProgress(100); return doneData as T; }
    const retryable = [408, 429, 502, 503, 504].includes(finished.status) || finished.status >= 500;
    if (!retryable || attempt >= CHUNK_RETRIES) throw uploadError(finished.status, doneData);
    await new Promise(resolve => setTimeout(resolve, 1500 * (attempt + 1)));
  }
}

function formFields(form: FormData): Record<string, unknown> {
  const fields: Record<string, unknown> = {};
  form.forEach((value, key) => {
    if (key === "file" || typeof value !== "string") return;
    if (value === "true" || value === "false") fields[key] = value === "true";
    else if (/^\d+$/.test(value) && key === "revision") fields[key] = Number(value);
    else fields[key] = value;
  });
  return fields;
}

/** Адрес начала частичной загрузки: `.../assets` → `.../uploads`, `/sales-files/upload` → `/sales-files/uploads`. */
function chunkStartPath(path: string): string {
  return `${path.replace(/\/(assets|upload)$/, "")}/uploads`;
}

function uploadFile(form: FormData): File | null {
  const file = form.get("file");
  return typeof File !== "undefined" && file instanceof File ? file : null;
}

/** Same-origin, streamed multipart upload with real progress and one auth renewal. */
export async function uploadMaterial<T>(path: string, form: FormData, onProgress: (percent: number) => void, signal?: AbortSignal): Promise<T> {
  const file = uploadFile(form);
  if (file && file.size > CHUNK_THRESHOLD_BYTES) {
    for (const base of [UPLOAD_PATH, FALLBACK_UPLOAD_PATH]) {
      try {
        return await uploadChunked<T>(`${base}${chunkStartPath(path)}`, file, formFields(form), onProgress, signal);
      } catch (error) {
        const failure = error as UploadFailure;
        // Старая сборка без частичной загрузки: 404/405 без JSON — пробуем обычный путь.
        if ((failure.status === 404 || failure.status === 405) && !failure.bodyWasJson) continue;
        throw error;
      }
    }
  }
  const send = async (base: string) => {
    try { return await uploadOnce<T>(base, path, form, onProgress, signal); }
    catch (error) {
      const failure = error as UploadFailure;
      if (failure.status === 401 && !signal?.aborted && await refreshSession()) return uploadOnce<T>(base, path, form, onProgress, signal);
      throw error;
    }
  };
  try {
    return await send(UPLOAD_PATH);
  } catch (error) {
    const failure = error as UploadFailure;
    // Старая сборка без прямого маршрута: путь /api/upload/ отдаёт 404 без JSON.
    if ((failure.status === 404 || failure.status === 405) && !failure.bodyWasJson) return send(FALLBACK_UPLOAD_PATH);
    throw error;
  }
}
