import { materialDownloadUrl } from "./download-url";
import { apiFetch, refreshSession } from "@/lib/api";

export type Material = {
  asset_id: string;
  original_filename: string;
  mime_type: string | null;
  size_bytes?: number | null;
  version?: number;
  order?: number;
};

export type MaterialKind = "table" | "document" | "text" | "pdf" | "image" | "video" | "audio" | "download";

export function fileExtension(name: string): string {
  return name.split(/[\\/]/).pop()?.split(".").slice(1).pop()?.toLowerCase() || "";
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

/** Same-origin, streamed multipart upload with real progress and one auth renewal. */
export async function uploadMaterial<T>(path: string, form: FormData, onProgress: (percent: number) => void, signal?: AbortSignal): Promise<T> {
  const send = () => new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/backend${path}`);
    xhr.withCredentials = true;
    xhr.timeout = 15 * 60 * 1000;
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100)); };
    const abort = () => xhr.abort();
    signal?.addEventListener("abort", abort, { once: true });
    xhr.onloadend = () => signal?.removeEventListener("abort", abort);
    xhr.onerror = () => reject(new Error("Соединение прервано. Обновите список файлов перед повторной загрузкой."));
    xhr.ontimeout = () => reject(new Error("Сервер не ответил вовремя. Проверьте список материалов перед повторной загрузкой."));
    xhr.onabort = () => reject(new DOMException("Загрузка отменена", "AbortError"));
    xhr.onload = () => {
      let data: Record<string, unknown>;
      try { data = JSON.parse(xhr.responseText); } catch { data = {}; }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
      else reject(Object.assign(new Error(String(data.error_message || data.detail || `Не удалось загрузить файл (${xhr.status})`)), { status: xhr.status }));
    };
    if (signal?.aborted) { reject(new DOMException("Загрузка отменена", "AbortError")); return; }
    xhr.send(form);
  });
  try { return await send(); }
  catch (error) {
    if ((error as { status?: number }).status === 401 && !signal?.aborted && await refreshSession()) return send();
    throw error;
  }
}
