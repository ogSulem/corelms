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

/** Same-origin, streamed multipart upload with real progress and one auth renewal. */
export async function uploadMaterial<T>(path: string, form: FormData, onProgress: (percent: number) => void, signal?: AbortSignal): Promise<T> {
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
