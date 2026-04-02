"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronLeft,
  File,
  FileAudio,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileVideo,
  Folder,
  HelpCircle,
} from "lucide-react";

import { AppShell } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LockIcon } from "@/components/ui/lock";
import { Modal } from "@/components/ui/modal";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";

type ModuleMeta = {
  id: string;
  title: string;
  description: string | null;
  difficulty: number;
  category: string | null;
  is_active: boolean;
};

type ModuleAsset = {
  asset_id: string;
  object_key: string;
  original_filename: string;
  mime_type: string | null;
  size_bytes?: number | null;
};

type AssetLike = {
  asset_id: string;
  mime_type: string | null;
  original_filename: string;
  size_bytes?: number | null;
};

type SubmoduleAsset = {
  asset_id: string;
  object_key?: string;
  original_filename: string;
  mime_type: string | null;
  size_bytes?: number | null;
  order?: number;
};

type InlineKind = "iframe" | "image" | "video" | "audio" | "pdf" | "text" | "office";

type Submodule = {
  id: string;
  module_id: string;
  title: string;
  order: number;
  quiz_id: string;
  requires_quiz: boolean;
  is_folder?: boolean;
  outline_path?: string | null;
};

type ProgressData = {
  module_id: string;
  total: number;
  passed: number;
  final_submodule_id: string | null;
  final_quiz_id: string | null;
  final_passed: boolean;
  final_best_score: number | null;
  completed: boolean;
  submodules: {
    submodule_id: string;
    quiz_id: string;
    read: boolean;
    passed: boolean;
    best_score: number | null;
    last_score?: number | null;
    last_passed?: boolean | null;
    locked?: boolean;
    locked_reason?: string | null;
    is_final?: boolean;
  }[];
};

export default function ModulePage() {
  const params = useParams<{ moduleId: string }>();
  const moduleId = params.moduleId;

  const [moduleMeta, setModuleMeta] = useState<ModuleMeta | null>(null);
  const [submodules, setSubmodules] = useState<Submodule[]>([]);
  const [progress, setProgress] = useState<ProgressData | null>(null);
  const [moduleAssets, setModuleAssets] = useState<ModuleAsset[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [assetNavPath, setAssetNavPath] = useState<string[]>([]);
  const [inlineUrl, setInlineUrl] = useState<string | null>(null);
  const [inlineMime, setInlineMime] = useState<string | null>(null);
  const [inlineName, setInlineName] = useState<string | null>(null);
  const [inlineText, setInlineText] = useState<string | null>(null);
  const [inlineAssetId, setInlineAssetId] = useState<string | null>(null);
  const [inlineRawUrl, setInlineRawUrl] = useState<string | null>(null);

  const inlineTextAbortRef = useRef<AbortController | null>(null);
  const presignCacheRef = useRef<Map<string, { url: string; expiresAt: number }>>(new Map());
  const [inlineKind, setInlineKind] = useState<InlineKind>("iframe");

  const [submodulePrimaryAssetById, setSubmodulePrimaryAssetById] = useState<Record<string, { asset_id: string; original_filename: string; mime_type: string | null } | null>>({});

  const [outlinePath, setOutlinePath] = useState<string[]>([]);

  const [folderModalOpen, setFolderModalOpen] = useState(false);
  const [folderModalTitle, setFolderModalTitle] = useState<string>("");
  const [folderModalFiles, setFolderModalFiles] = useState<Array<{ full: string[]; asset: SubmoduleAsset }>>([]);
  const [folderModalNavPath, setFolderModalNavPath] = useState<string[]>([]);
  const [folderModalLoading, setFolderModalLoading] = useState(false);

  const [fileModalOpen, setFileModalOpen] = useState(false);

  const [assetsOnlyOpenMarked, setAssetsOnlyOpenMarked] = useState(false);

  function decodeLegacyPercentUnicode(input: string): string {
    const raw = String(input || "").trim();
    if (!raw) return "";
    try {
      const replaced = raw.replace(/%[uU]([0-9a-fA-F]{4})/g, (_, hex) => {
        try {
          return String.fromCharCode(Number.parseInt(hex, 16));
        } catch {
          return _;
        }
      });
      const decoded = decodeURIComponent(replaced);
      return decoded.normalize("NFC");
    } catch {
      try {
        return raw.normalize("NFC");
      } catch {
        return raw;
      }
    }
  }

  function openFileFromFolder(a: SubmoduleAsset) {
    const assetId = String(a?.asset_id || "").trim();
    if (!assetId) return;
    setFileModalOpen(true);
    void onOpenInline({
      asset_id: assetId,
      mime_type: a.mime_type ?? null,
      original_filename: String(a.original_filename || ""),
    });
  }

  function formatAssetTitle(name: string): string {
    const raw = decodeLegacyPercentUnicode(String(name || "").trim());
    return raw
      .replace(/^\s*\d{1,3}\s*[\.)]\s*/u, "")
      .replace(/^\s*\d{1,3}\s*[-_:]\s*/u, "")
      .trim();
  }

  function naturalPrefixOrder(name: string, fallback: number): number {
    const raw = decodeLegacyPercentUnicode(String(name || "").trim());
    const m = /^\s*(\d{1,6})/u.exec(raw);
    if (!m) return fallback;
    const n = Number.parseInt(m[1] || "", 10);
    return Number.isFinite(n) ? n : fallback;
  }

  const fetchModuleData = async () => {
    if (!moduleId) return;
    try {
      setError(null);
      setLoading(true);

      const [meta, s, p, ma] = await Promise.all([
        apiFetch<ModuleMeta>(`/modules/${moduleId}`),
        apiFetch<Submodule[]>(`/modules/${moduleId}/submodules`),
        apiFetch<ProgressData>(`/progress/modules/${moduleId}`),
        apiFetch<{ assets: ModuleAsset[] }>(`/modules/${moduleId}/assets`),
      ]);

      setModuleMeta(meta);
      setSubmodules((s || []).map((item: any) => ({ ...item, id: String(item.id), requires_quiz: Boolean(item?.requires_quiz ?? true) })));
      setProgress(p);
      setModuleAssets((ma?.assets || []).map(item => ({ ...item, asset_id: String(item.asset_id) })));
    } catch (e) {
      const anyErr = e as any;
      const msg = e instanceof Error ? e.message : "Не удалось загрузить модуль. Проверьте подключение.";
      const rid = String(anyErr?.requestId || anyErr?.request_id || "").trim();
      setError((msg || "Не удалось загрузить модуль. Проверьте подключение.") + (rid ? ` (код: ${rid})` : ""));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchModuleData();
  }, [moduleId]);

  useEffect(() => {
    setAssetNavPath([]);
    setInlineUrl(null);
    setInlineMime(null);
    setInlineName(null);
    setInlineText(null);
    setInlineAssetId(null);
    setInlineRawUrl(null);
    setInlineKind("iframe");
    setOutlinePath([]);
    setFolderModalOpen(false);
    setFolderModalTitle("");
    setFolderModalFiles([]);
    setFolderModalNavPath([]);
    setFolderModalLoading(false);
    setFileModalOpen(false);
    setAssetsOnlyOpenMarked(false);
  }, [moduleId]);

  useEffect(() => {
    if (!moduleId) return;
    if (assetsOnlyOpenMarked) return;
    if (loading) return;
    if ((submodules || []).length !== 0) return;
    if ((moduleAssets || []).length === 0) return;
    setAssetsOnlyOpenMarked(true);
    (async () => {
      try {
        await apiFetch(`/modules/${encodeURIComponent(String(moduleId))}/open`, { method: "POST" });
      } catch {
        // ignore
      }
      try {
        const p = await apiFetch<ProgressData>(`/progress/modules/${moduleId}`);
        setProgress(p);
      } catch {
        // ignore
      }
    })();
  }, [assetsOnlyOpenMarked, loading, moduleAssets, moduleId, submodules]);

  async function openFolderCatalog(nextPath: string[]) {
    const title = nextPath[nextPath.length - 1] || "Каталог";
    const parentKey = nextPath.slice(0, -1).join("/");
    setFolderModalTitle(title);
    setFolderModalOpen(true);
    setFolderModalNavPath([]);
    setFolderModalLoading(true);
    try {
      // Folder lessons are represented as a single submodule with is_folder=true.
      // Its assets contain the whole folder contents (including nested paths).
      const folder = (submodules || []).find((s: Submodule) => {
        const isFolder = Boolean((s as any)?.is_folder);
        if (!isFolder) return false;
        if (String(s.title || "").trim() !== String(title || "").trim()) return false;
        const p = String((s as any)?.outline_path || "").trim();
        if (!parentKey) return !p;
        return p === parentKey;
      });

      const fileRows: Array<{ full: string[]; asset: SubmoduleAsset }> = [];

      if (folder) {
        try {
          const resp = await apiFetch<{ assets: SubmoduleAsset[] }>(
            `/modules/submodules/${encodeURIComponent(String(folder.id))}/assets`
          );
          const assets = (resp?.assets || []).slice();
          assets.sort((a, b) => Number(a?.order || 0) - Number(b?.order || 0));
          for (const a of assets) {
            const rawName = String(a?.original_filename || "");
            const decodedName = decodeLegacyPercentUnicode(rawName).replaceAll("\\", "/");
            const segs = decodedName.split("/").map((s) => String(s || "").trim()).filter(Boolean);
            const full = segs.length ? segs : [decodeLegacyPercentUnicode(rawName).trim() || "Файл"];
            fileRows.push({ full, asset: a });
          }
        } catch {
          // ignore
        }
      }
      fileRows.sort((a, b) => a.full.join("/").localeCompare(b.full.join("/"), undefined, { sensitivity: "base" }));
      setFolderModalFiles(fileRows);
    } finally {
      setFolderModalLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        const wants = (submodules || []).filter((s: Submodule) => !s.requires_quiz);
        if (!wants.length) {
          if (!cancelled) setSubmodulePrimaryAssetById({});
          return;
        }

        const next: Record<string, { asset_id: string; original_filename: string; mime_type: string | null } | null> = {};

        await Promise.all(
          wants.map(async (s: Submodule) => {
            try {
              const resp = await apiFetch<{ assets: Array<{ asset_id: string; original_filename: string; mime_type: string | null; order?: number }> }>(
                `/modules/submodules/${encodeURIComponent(String(s.id))}/assets`
              );
              const assets = (resp?.assets || []).slice();
              assets.sort((a, b) => Number(a?.order || 0) - Number(b?.order || 0));
              const a0 = assets[0];
              next[String(s.id)] = a0
                ? {
                    asset_id: String(a0.asset_id || ""),
                    original_filename: String(a0.original_filename || ""),
                    mime_type: a0.mime_type ?? null,
                  }
                : null;
            } catch {
              next[String(s.id)] = null;
            }
          })
        );

        if (!cancelled) setSubmodulePrimaryAssetById(next);
      } catch {
        if (!cancelled) setSubmodulePrimaryAssetById({});
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [submodules]);

  useEffect(() => {
    if (!moduleId) return;
    let inFlight = false;
    let lastReloadAt = 0;
    let lastHiddenAt = 0;
    const safeReload = (opts?: { force?: boolean }) => {
      const now = Date.now();
      if (!opts?.force && now - lastReloadAt < 3000) return;
      if (inFlight) return;
      inFlight = true;
      lastReloadAt = now;
      Promise.resolve(fetchModuleData()).finally(() => {
        inFlight = false;
      });
    };

    const onRefresh = (e: any) => {
      try {
        const reason = String(e?.detail?.reason || "").trim().toLowerCase();
        if (reason === "keepalive") return;
        if (reason === "progress") {
          safeReload({ force: true });
          return;
        }
      } catch {
        // ignore
      }
      safeReload();
    };
    const onFocus = () => safeReload();
    const onVisibility = () => {
      const st = document.visibilityState;
      if (st === "hidden") {
        lastHiddenAt = Date.now();
        return;
      }
      if (st === "visible") {
        const hiddenForMs = lastHiddenAt ? Date.now() - lastHiddenAt : 0;
        if (hiddenForMs >= 30_000) safeReload();
      }
    };

    window.addEventListener("corelms:refresh-me", onRefresh as EventListener);
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("corelms:refresh-me", onRefresh as EventListener);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [moduleId]);

  async function onOpenAsset(assetId: string) {
    try {
      const sid = String(assetId || "").trim();
      if (!sid) return;
      const url = await presignViewUrl(sid);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("corelms:toast", {
            detail: {
              title: "НЕ УДАЛОСЬ ОТКРЫТЬ ФАЙЛ",
              description: msg || "Проверьте доступ к хранилищу и попробуйте снова",
            },
          })
        );
      }
    }
  }

  function closeInline() {
    try {
      inlineTextAbortRef.current?.abort();
    } catch {
      // ignore
    }
    inlineTextAbortRef.current = null;
    setInlineUrl(null);
    setInlineMime(null);
    setInlineName(null);
    setInlineText(null);
    setInlineAssetId(null);
    setInlineRawUrl(null);
  }

  function closeFileModal() {
    setFileModalOpen(false);
    closeInline();
  }

  function getExtFromNameOrKey(name: string, objectKey?: string | null): string {
    const pick = (s: string): string => {
      let raw = String(s || "").trim();
      if (!raw) return "";
      try {
        raw = raw.replaceAll("\\", "/");
        if (raw.includes("/")) raw = raw.split("/").pop() || raw;
      } catch {
        // ignore
      }
      const idx = raw.lastIndexOf(".");
      if (idx < 0) return "";
      const ext = raw.slice(idx + 1).trim().toLowerCase();
      if (!ext) return "";
      if (ext.length > 8) return "";
      if (!/^[a-z0-9]+$/.test(ext)) return "";
      return ext;
    };
    return pick(name) || pick(String(objectKey || ""));
  }

  function getMaterialTag(a: { original_filename: string; mime_type: string | null; object_key?: string | null } | null): string {
    if (!a) return "МАТЕРИАЛЫ";
    const name = String(a.original_filename || "").trim();
    const mime = String(a.mime_type || "").toLowerCase();
    const ext = getExtFromNameOrKey(name, (a as any)?.object_key);

    if (isTableFile(a)) return "ТАБЛИЦА";

    if (mime.startsWith("video/") || ["mp4", "webm", "mov", "mkv"].includes(ext)) return "ВИДЕО";
    if (mime.includes("pdf") || ext === "pdf") return "PDF";
    if (mime.startsWith("image/") || ["png", "jpg", "jpeg", "webp", "gif", "svg"].includes(ext)) return "ИЗОБРАЖЕНИЕ";
    if (mime.startsWith("audio/") || ["mp3", "wav", "ogg", "m4a"].includes(ext)) return "АУДИО";
    if (ext) return `.${ext.toUpperCase()}`;
    return "ФАЙЛ";
  }

  function isTableFile(a: { original_filename: string; mime_type: string | null; object_key?: string | null } | null): boolean {
    if (!a) return false;
    const name = String(a.original_filename || "").toLowerCase();
    const mime = String(a.mime_type || "").toLowerCase();
    const ext = getExtFromNameOrKey(name, (a as any)?.object_key);
    if (["xls", "xlsx", "csv"].includes(ext)) return true;
    if (mime.includes("spreadsheet") || mime.includes("ms-excel")) return true;
    return false;
  }

  async function onDownloadAsset(assetId: string) {
    const aid = String(assetId || "").trim();
    if (!aid) return;
    try {
      const r = await apiFetch<{ asset_id: string; download_url: string }>(
        `/assets/${encodeURIComponent(aid)}/presign-download?action=download`,
        { method: "GET" }
      );
      const url = String((r as any)?.download_url || "").trim();
      if (!url) throw new Error("missing download url");
      if (typeof window !== "undefined") {
        window.open(url, "_blank", "noopener,noreferrer");
      }
    } catch {
      // ignore
    }
  }

  function streamUrl(assetId: string): string {
    return `/api/backend/assets/${encodeURIComponent(String(assetId || "").trim())}/stream`;
  }

  async function presignViewUrl(assetId: string): Promise<string> {
    const sid = String(assetId || "").trim();

    const now = Date.now();
    const cached = presignCacheRef.current.get(sid);
    if (cached && cached.url && cached.expiresAt > now) return cached.url;

    const r = await apiFetch<{ asset_id: string; download_url: string }>(
      `/assets/${encodeURIComponent(sid)}/presign-download?action=view`,
      { method: "GET" }
    );
    const u = String((r as any)?.download_url || "").trim();
    if (!u) throw new Error("missing presigned url");

    presignCacheRef.current.set(sid, { url: u, expiresAt: now + 2 * 60 * 1000 });
    return u;
  }

  async function onOpenInline(a: AssetLike) {
    try {
      const stream = streamUrl(a.asset_id);
      const rawName = String(a.original_filename || "").trim();
      const mime = String(a.mime_type || "").toLowerCase();
      const ext = getExtFromNameOrKey(rawName, (a as any)?.object_key);

      try {
        inlineTextAbortRef.current?.abort();
      } catch {
        // ignore
      }
      inlineTextAbortRef.current = null;

      setInlineMime(a.mime_type || null);
      setInlineName(rawName || null);
      setInlineAssetId(String(a.asset_id || "").trim() || null);

    const isOffice = ["doc", "docx", "ppt", "pptx", "xls", "xlsx"].includes(ext);
    const isTextLike = ["csv", "json"].includes(ext);
    const isMedia = ["mp4", "webm", "mov", "mkv", "mp3", "wav", "ogg", "m4a"].includes(ext);

    const kind: InlineKind =
      mime.includes("pdf") || ext === "pdf"
        ? "pdf"
        : mime.startsWith("audio/") || ["mp3", "wav", "ogg", "m4a"].includes(ext)
          ? "audio"
          : mime.startsWith("video/") || ["mp4", "webm", "mov", "mkv"].includes(ext)
            ? "video"
            : mime.startsWith("image/") || ["png", "jpg", "jpeg", "webp", "gif", "svg"].includes(ext)
              ? "image"
              : mime.startsWith("text/") || ["txt", "md"].includes(ext) || isTextLike
                ? "text"
                : isOffice
                  ? "office"
                  : "iframe";

    setInlineKind(kind);

    const targetUrl =
      kind === "office" || kind === "video" || kind === "audio" || kind === "pdf" || kind === "image"
        ? await presignViewUrl(a.asset_id)
        : stream;

    if (kind === "office") {
      setInlineRawUrl(targetUrl);
      try {
        const officeUrl = `https://view.officeapps.live.com/op/embed.aspx?src=${encodeURIComponent(targetUrl)}`;
        setInlineUrl(officeUrl);
      } catch {
        setInlineUrl(targetUrl);
      }
    } else {
      setInlineRawUrl(null);
      if (targetUrl) setInlineUrl(targetUrl);
    }

    if (kind === "text") {
      const maxTextBytes = 2_000_000;
      const sz = Number((a as any)?.size_bytes ?? null);
      if (Number.isFinite(sz) && sz > maxTextBytes) {
        try {
          if (typeof window !== "undefined") {
            window.open(targetUrl, "_blank", "noopener,noreferrer");
            window.dispatchEvent(
              new CustomEvent("corelms:toast", {
                detail: {
                  title: "ФАЙЛ СЛИШКОМ БОЛЬШОЙ ДЛЯ ПРЕДПРОСМОТРА",
                  description: "Открываю в новой вкладке.",
                },
              })
            );
          }
        } catch {
          // ignore
        }
        closeInline();
        return;
      }

      const ctrl = new AbortController();
      inlineTextAbortRef.current = ctrl;
      const res = await fetch(targetUrl, { credentials: "include", signal: ctrl.signal });
      if (!res.ok) {
        if (res.status === 404) {
          throw new Error("Файл удалён из хранилища (404). Переимпортируйте модуль или загрузите файл заново.");
        }
        throw new Error(`Не удалось загрузить текст (код ${res.status}).`);
      }
      const txt = await res.text();
      setInlineText(txt);
    } else {
      setInlineText(null);
    }

    // Auto-scroll to preview for non-media files to keep focus on content
    if (!isMedia && typeof window !== "undefined") {
      window.setTimeout(() => {
        const el = document.getElementById("asset-preview-container");
        el?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    }
    } catch (e) {
      const anyErr = e as any;
      if (anyErr?.name === "AbortError") return;
      closeInline();
      const msg = e instanceof Error ? e.message : String(e);
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("corelms:toast", {
            detail: {
              title: "НЕ УДАЛОСЬ ОТКРЫТЬ ФАЙЛ",
              description: msg || "Проверьте доступ к хранилищу и попробуйте снова",
            },
          })
        );
      }
    }
  }

  function isViewableMaterial(a: { original_filename: string; mime_type: string | null; object_key?: string | null }): boolean {
    const name = String(a?.original_filename || "").toLowerCase();
    const mime = String(a?.mime_type || "").toLowerCase();
    const ext = getExtFromNameOrKey(name, (a as any)?.object_key);
    if (mime.includes("pdf") || ext === "pdf") return true;
    if (mime.startsWith("image/") || ["png", "jpg", "jpeg", "webp", "gif", "svg"].includes(ext)) return true;
    if (mime.startsWith("video/") || ["mp4", "webm", "mov", "mkv"].includes(ext)) return true;
    if (mime.startsWith("audio/") || ["mp3", "wav", "ogg", "m4a"].includes(ext)) return true;
    if (mime.startsWith("text/") || ["txt", "md", "csv", "json"].includes(ext)) return true;
    if (["doc", "docx", "ppt", "pptx", "xls", "xlsx"].includes(ext)) return true;
    return false;
  }

  function getAssetIcon(a: { original_filename: string; mime_type: string | null; object_key?: string | null }) {
    const name = String(a?.original_filename || "").toLowerCase();
    const mime = String(a?.mime_type || "").toLowerCase();
    const ext = getExtFromNameOrKey(name, (a as any)?.object_key);

    if (mime.includes("pdf") || ext === "pdf") return FileText;
    if (mime.startsWith("image/") || ["png", "jpg", "jpeg", "webp", "gif", "svg"].includes(ext)) return FileImage;
    if (mime.startsWith("video/") || ["mp4", "webm", "mov", "mkv"].includes(ext)) return FileVideo;
    if (mime.startsWith("audio/") || ["mp3", "wav", "ogg", "m4a"].includes(ext)) return FileAudio;
    if (["xls", "xlsx", "csv"].includes(ext)) return FileSpreadsheet;
    if (mime.startsWith("text/") || ["txt", "md", "json"].includes(ext)) return FileText;
    if (["doc", "docx", "ppt", "pptx"].includes(ext)) return FileText;

    return File;
  }

  const assetBrowser = useMemo(() => {
    const sep = "/";
    const safeSeg = (s: string) =>
      decodeLegacyPercentUnicode(String(s || "").trim())
        .replaceAll("\\", "/")
        .split("/")
        .map((x) => String(x || "").trim())
        .filter(Boolean);
    const entries: Array<
      | { type: "dir"; name: string; path: string[] }
      | { type: "file"; name: string; path: string[]; asset: ModuleAsset }
    > = [];

    const dirs = new Map<string, Set<string>>();
    const files: Array<{ full: string[]; asset: ModuleAsset }> = [];

    for (const a of moduleAssets || []) {
      const raw = String((a as any)?.original_filename || "").trim();
      if (!raw) continue;
      const full = safeSeg(raw);
      if (!full.length) continue;
      files.push({ full, asset: a });
    }

    const cur = (assetNavPath || []).filter(Boolean);
    const curKey = cur.join(sep);

    for (const f of files) {
      const parent = f.full.slice(0, -1);
      const fileName = f.full[f.full.length - 1];
      const parentKey = parent.join(sep);
      if (!dirs.has(parentKey)) dirs.set(parentKey, new Set<string>());
      for (let i = 0; i < parent.length; i++) {
        const pk = parent.slice(0, i).join(sep);
        const child = parent[i];
        if (!dirs.has(pk)) dirs.set(pk, new Set<string>());
        dirs.get(pk)!.add(child);
      }
      if (!dirs.has("")) dirs.set("", new Set<string>());
      if (parent.length >= 1) dirs.get("")!.add(parent[0]);

      if (parentKey === curKey) {
        entries.push({ type: "file", name: fileName, path: f.full, asset: f.asset });
      }
    }

    const childDirs = Array.from(dirs.get(curKey) || new Set<string>());
    for (const d of childDirs) {
      entries.push({ type: "dir", name: d, path: cur.concat([d]) });
    }

    entries.sort((a, b) => {
      if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
      const ao = naturalPrefixOrder(a.name, 999999);
      const bo = naturalPrefixOrder(b.name, 999999);
      if (ao !== bo) return ao - bo;
      return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
    });

    return {
      current: cur,
      entries,
      hasAny: (moduleAssets || []).length > 0,
    };
  }, [assetNavPath, moduleAssets]);

  const folderBrowser = useMemo(() => {
    const sep = "/";
    const entries: Array<
      | { type: "dir"; name: string; path: string[] }
      | { type: "file"; name: string; path: string[]; asset: SubmoduleAsset }
    > = [];

    const cur = folderModalNavPath || [];
    const curKey = cur.join(sep);

    const dirs = new Map<string, Set<string>>();

    for (const f of folderModalFiles || []) {
      const parent = f.full.slice(0, -1);
      const fileName = f.full[f.full.length - 1];
      const parentKey = parent.join(sep);
      if (!dirs.has(parentKey)) dirs.set(parentKey, new Set<string>());
      for (let i = 0; i < parent.length; i++) {
        const pk = parent.slice(0, i).join(sep);
        const child = parent[i];
        if (!dirs.has(pk)) dirs.set(pk, new Set<string>());
        dirs.get(pk)!.add(child);
      }
      if (!dirs.has("")) dirs.set("", new Set<string>());
      if (parent.length >= 1) dirs.get("")!.add(parent[0]);

      if (parentKey === curKey) {
        entries.push({ type: "file", name: fileName, path: f.full, asset: f.asset });
      }
    }

    const childDirs = Array.from(dirs.get(curKey) || new Set<string>());
    for (const d of childDirs) {
      entries.push({ type: "dir", name: d, path: cur.concat([d]) });
    }

    entries.sort((a, b) => {
      if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
      return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
    });

    return {
      current: cur,
      entries,
      hasAny: (folderModalFiles || []).length > 0,
    };
  }, [folderModalFiles, folderModalNavPath]);

  const canInlinePreview = useMemo(() => {
    if (!inlineUrl) return false;
    if (inlineKind === "office") return true;
    if (inlineKind === "pdf") return true;
    if (inlineKind === "image") return true;
    if (inlineKind === "video") return true;
    if (inlineKind === "audio") return true;
    if (inlineKind === "text") return true;
    return false;
  }, [inlineKind, inlineUrl]);

  const progressMap = useMemo(() => {
    const m = new Map<string, any>();
    progress?.submodules.forEach((s: any) => m.set(s.submodule_id, s));
    return m;
  }, [progress]);

  const displayedSubmodules = useMemo(() => {
    const key = outlinePath.join("/");
    return (submodules || [])
      .filter((s) => {
        const p = String((s as any)?.outline_path || "").trim();
        const isFolder = Boolean((s as any)?.is_folder);
        if (isFolder) return false;
        if (!key) return !p;
        return p === key;
      })
      .slice()
      .sort((a: any, b: any) => {
        const aOrder = Number(a?.order);
        const bOrder = Number(b?.order);
        const aoN = Number.isFinite(aOrder) ? aOrder : 999999;
        const boN = Number.isFinite(bOrder) ? bOrder : 999999;
        if (aoN !== boN) return aoN - boN;
        const at = String(a?.title || "");
        const bt = String(b?.title || "");
        const ao = naturalPrefixOrder(at, 999999);
        const bo = naturalPrefixOrder(bt, 999999);
        if (ao !== bo) return ao - bo;
        return at.localeCompare(bt, undefined, { sensitivity: "base" });
      });
  }, [outlinePath, submodules]);

  const displayedOrderStartsAtZero = useMemo(() => {
    if (!displayedSubmodules.length) return false;
    let min = Number.POSITIVE_INFINITY;
    for (const s of displayedSubmodules as any[]) {
      const o = Number((s as any)?.order);
      if (!Number.isFinite(o)) continue;
      if (o < min) min = o;
    }
    return Number.isFinite(min) && min <= 0;
  }, [displayedSubmodules]);

  const folderSubmodules = useMemo(() => {
    const key = outlinePath.join("/");
    return (submodules || []).filter((s) => {
      const isFolder = Boolean((s as any)?.is_folder);
      if (!isFolder) return false;
      const p = String((s as any)?.outline_path || "").trim();
      if (!key) return !p;
      return p === key;
    });
  }, [outlinePath, submodules]);

  const rootFolderSubmodules = useMemo(() => {
    return (submodules || []).filter((s) => {
      const isFolder = Boolean((s as any)?.is_folder);
      if (!isFolder) return false;
      const p = String((s as any)?.outline_path || "").trim();
      return !p;
    });
  }, [submodules]);

  const outlineFolders = useMemo(() => {
    const baseKey = outlinePath.join("/");
    const out = new Set<string>();
    for (const s of submodules || []) {
      const p = String((s as any)?.outline_path || "").trim();
      if (!p) continue;
      const parts = p.split("/").filter(Boolean);
      if (!parts.length) continue;
      if (baseKey) {
        if (p === baseKey) continue;
        if (!p.startsWith(baseKey + "/")) continue;
        const next = p.slice(baseKey.length + 1).split("/").filter(Boolean)[0];
        if (next) out.add(next);
      } else {
        out.add(parts[0]);
      }
    }
    return Array.from(out).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
  }, [outlinePath, submodules]);

  function hasAttempt(p: any): boolean {
    if (!p) return false;
    const scorePresent = p.last_score !== undefined && p.last_score !== null;
    const passedPresent = p.last_passed !== undefined && p.last_passed !== null;
    return Boolean(scorePresent || passedPresent);
  }

  function displayScore(p: any): number | null {
    if (!hasAttempt(p)) return null;
    return typeof p?.last_score === "number" ? p.last_score : 0;
  }

  const currentSubmoduleId = useMemo(() => {
    if (!submodules.length || !progressMap.size) return null;
    for (const s of submodules) {
      const st = progressMap.get(s.id);
      if (st?.locked) continue;
      const rq = Boolean((s as any)?.requires_quiz ?? true);
      if (!rq) continue;
      if (!st?.passed) return s.id;
    }
    return null;
  }, [submodules, progressMap]);

  const quizTotals = useMemo(() => {
    if (!progress) return { passed: 0, total: 0 };
    return { passed: progress.passed, total: progress.total };
  }, [progress]);

  const finalExamLocked = useMemo(() => {
    if (!progress) return true;
    return progress.submodules.some((s: any) => {
      const rq = typeof s?.requires_quiz === "boolean" ? Boolean(s.requires_quiz) : true;
      return rq ? !s.passed : false;
    });
  }, [progress]);

  const continueHref = useMemo(() => {
    if (currentSubmoduleId) {
      return `/submodules/${encodeURIComponent(currentSubmoduleId)}?module=${encodeURIComponent(moduleId)}`;
    }
    if (progress?.final_quiz_id && !finalExamLocked && !progress.final_passed) {
      return `/quizzes/${encodeURIComponent(String(progress.final_quiz_id))}?module=${encodeURIComponent(moduleId)}`;
    }
    return "";
  }, [currentSubmoduleId, finalExamLocked, moduleId, progress?.final_passed, progress?.final_quiz_id]);

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-6 py-10">
            <div className="flex items-start justify-between gap-6">
              <div className="flex-1">
                <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900] mb-2">Программа обучения</div>
                <h1 className="text-4xl font-black tracking-tighter text-zinc-950 uppercase leading-none">
                  {moduleMeta?.title || (loading ? "Загрузка…" : "Модуль")}
                </h1>
                {progress?.completed ? (
                  <div className="mt-4 inline-flex items-center gap-2 rounded-2xl border border-[#284e13]/25 bg-[#284e13]/10 px-4 py-2 text-[10px] font-black uppercase tracking-widest text-[#284e13]">
                    МОДУЛЬ ПРОЙДЕН
                  </div>
                ) : null}
                <div className="mt-6 max-w-md">
                  <div className="flex items-center justify-between text-[10px] font-black uppercase tracking-widest text-zinc-600 mb-2">
                    <div>Прогресс модуля</div>
                    <div className="tabular-nums text-[#284e13]">
                      {quizTotals.passed} / {quizTotals.total}
                    </div>
                  </div>
                  <div className="h-1 w-full rounded-full bg-zinc-200 overflow-hidden">
                    <div 
                      className="h-full bg-[#fe9900] transition-all duration-1000"
                      style={{ width: `${quizTotals.total > 0 ? Math.round((quizTotals.passed / quizTotals.total) * 100) : 0}%` }}
                    />
                  </div>
                </div>

                <div className="mt-6 flex flex-wrap items-center gap-3">
                  {continueHref ? (
                    <Link href={continueHref}>
                      <Button className="h-12 rounded-2xl px-8 font-black uppercase tracking-widest text-[10px]">
                        Продолжить обучение
                      </Button>
                    </Link>
                  ) : (
                    <Button disabled className="h-12 rounded-2xl px-8 font-black uppercase tracking-widest text-[10px]">
                      Продолжить обучение
                    </Button>
                  )}
                  {!continueHref && progress?.final_quiz_id && finalExamLocked ? (
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">
                      Сначала завершите все уроки
                    </div>
                  ) : null}
                </div>
              </div>
              <Link href="/modules">
                <Button
                  variant="ghost"
                  size="sm"
                  className="rounded-xl"
                >
                  <ChevronLeft className="mr-2 h-4 w-4" />
                  назад
                </Button>
              </Link>
            </div>

        {error ? (
          <div className="mt-8 rounded-3xl border border-red-500/30 bg-red-500/10 p-12 text-center shadow-2xl">
            <div className="text-red-200 text-lg font-medium mb-6">{error}</div>
            <Button onClick={() => fetchModuleData()} variant="outline" className="border-red-500/30 hover:bg-red-500/15 h-12 px-8 rounded-xl">
              Попробовать снова
            </Button>
          </div>
        ) : (
          <div className="mt-8 grid gap-8 lg:grid-cols-3">
            <Card data-corelms="module-assets-card" className="lg:col-span-1 relative overflow-hidden border border-zinc-200 bg-white/70 backdrop-blur-md rounded-[28px] shadow-2xl shadow-zinc-950/10">
              <div className="absolute left-0 top-0 h-full w-[2px] bg-gradient-to-b from-[#fe9900]/60 to-transparent" />
              <CardHeader className="p-8">
                <CardTitle className="text-xs font-black uppercase tracking-[0.3em] text-zinc-500">Материалы</CardTitle>
              </CardHeader>
              <CardContent className="px-8 pb-8 pt-0">
                {loading ? (
                  <div className="space-y-4">
                    <Skeleton className="h-16 w-full rounded-2xl bg-zinc-100" />
                    <Skeleton className="h-16 w-full rounded-2xl bg-zinc-100" />
                  </div>
                ) : !assetBrowser.hasAny && !(outlinePath.length ? folderSubmodules.length : rootFolderSubmodules.length) ? (
                  <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600 py-12 text-center border border-dashed border-zinc-200 rounded-2xl">
                    Нет файлов
                  </div>
                ) : (
                  <div>
                    {(outlinePath.length ? folderSubmodules : rootFolderSubmodules).length ? (
                      <div className="mb-6">
                        <div className="mt-3 grid gap-3">
                          {(outlinePath.length ? folderSubmodules : rootFolderSubmodules)
                            .slice()
                            .sort((a: any, b: any) => {
                              const aOrder = Number(a?.order);
                              const bOrder = Number(b?.order);
                              const aoN = Number.isFinite(aOrder) ? aOrder : 999999;
                              const boN = Number.isFinite(bOrder) ? bOrder : 999999;
                              if (aoN !== boN) return aoN - boN;
                              const ao = naturalPrefixOrder(String(a?.title || ""), 999999);
                              const bo = naturalPrefixOrder(String(b?.title || ""), 999999);
                              if (ao !== bo) return ao - bo;
                              return String(a?.title || "").localeCompare(String(b?.title || ""), undefined, { sensitivity: "base" });
                            })
                            .map((s: Submodule) => {
                            const folderName = String(s.title || "").trim() || "Папка";
                            const nextPath = outlinePath.concat([folderName]);
                            return (
                              <button
                                key={`folder-material:${String(s.id)}`}
                                type="button"
                                onClick={() => {
                                  void openFolderCatalog(nextPath);
                                }}
                                className="group flex items-center justify-between gap-4 rounded-2xl border border-zinc-200 bg-white/70 p-4 transition-all duration-300 hover:bg-white text-left"
                              >
                                <div className="flex items-start gap-3 min-w-0 flex-1">
                                  <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-zinc-200 bg-white text-zinc-700">
                                    <Folder className="h-4 w-4" />
                                  </div>
                                  <div className="min-w-0 flex-1">
                                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Папка</div>
                                    <div className="mt-1 text-sm font-bold text-zinc-950 transition-colors break-words whitespace-normal leading-snug">
                                      {folderName}
                                    </div>
                                  </div>
                                </div>
                                <span className="shrink-0 rounded-xl bg-zinc-50 border border-zinc-200 px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-600 transition-all active:scale-95">
                                  открыть
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    ) : null}

                    {assetBrowser.hasAny && (assetBrowser.entries.length > 0 || assetBrowser.current.length > 0) ? (
                      <>
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div className="flex flex-wrap items-center gap-2 text-[10px] font-black uppercase tracking-widest text-zinc-600">
                            <button
                              type="button"
                              onClick={() => setAssetNavPath([])}
                              className={
                                "rounded-lg px-2 py-1 transition " +
                                (!assetBrowser.current.length ? "bg-zinc-100 text-zinc-900" : "text-zinc-600 hover:bg-zinc-50")
                              }
                            >
                              /
                            </button>
                            {assetBrowser.current.map((seg, idx) => (
                              <div key={`bc:${idx}`} className="flex items-center gap-2">
                                <span className="text-zinc-400">/</span>
                                <button
                                  type="button"
                                  onClick={() => setAssetNavPath(assetBrowser.current.slice(0, idx + 1))}
                                  className={
                                    "rounded-lg px-2 py-1 transition " +
                                    (idx === assetBrowser.current.length - 1
                                      ? "bg-zinc-100 text-zinc-900"
                                      : "text-zinc-600 hover:bg-zinc-50")
                                  }
                                >
                                  {seg}
                                </button>
                              </div>
                            ))}
                          </div>
                          {assetBrowser.current.length ? (
                            <button
                              type="button"
                              onClick={() => setAssetNavPath(assetBrowser.current.slice(0, -1))}
                              className="h-9 rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                            >
                              Назад
                            </button>
                          ) : null}
                        </div>

                        <div className="mt-5 grid gap-3">
                          {!assetBrowser.entries.length ? null : (
                            assetBrowser.entries.map((e, idx) => {
                              if (e.type === "dir") {
                                return (
                                  <button
                                    key={`dir:${e.path.join("/")}`}
                                    type="button"
                                    onClick={() => setAssetNavPath(e.path)}
                                    className="group flex items-center justify-between gap-4 rounded-2xl border border-zinc-200 bg-white/70 p-4 transition-all duration-300 hover:bg-white"
                                  >
                                    <div className="flex items-center gap-3 min-w-0">
                                      <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-zinc-200 bg-white text-zinc-700">
                                        <Folder className="h-4 w-4" />
                                      </div>
                                      <div className="min-w-0">
                                        <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Папка</div>
                                        <div className="mt-1 truncate text-sm font-bold text-zinc-950 transition-colors">
                                          {e.name}
                                        </div>
                                      </div>
                                    </div>
                                    <span className="text-zinc-400 font-black">→</span>
                                  </button>
                                );
                              }

                              const Icon = getAssetIcon({ original_filename: e.name, mime_type: e.asset.mime_type, object_key: (e.asset as any)?.object_key });
                              return (
                                <button
                                  key={`file:${e.path.join("/")}:${e.asset.asset_id}`}
                                  type="button"
                                  onClick={() => void onOpenInline({ ...(e.asset as any), original_filename: e.asset.original_filename })}
                                  className="group flex items-center justify-between gap-4 rounded-2xl border border-zinc-200 bg-white/70 p-4 transition-all duration-300 hover:bg-white text-left"
                                >
                                  <div className="flex items-center gap-3 min-w-0">
                                    <span className="shrink-0 text-[10px] font-black uppercase tracking-widest text-zinc-500 tabular-nums">
                                      {String(idx + 1).padStart(2, "0")}
                                    </span>
                                    <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-zinc-200 bg-white text-zinc-700">
                                      <Icon className="h-4 w-4" />
                                    </div>
                                    <div className="min-w-0">
                                      <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Файл</div>
                                      <div className="mt-1 min-w-0 truncate text-sm font-bold text-zinc-950 transition-colors">
                                        {formatAssetTitle(e.name) || e.name}
                                      </div>
                                    </div>
                                  </div>
                                  <span className="shrink-0 rounded-xl bg-[#fe9900]/10 border border-[#fe9900]/25 px-3 py-2 text-[9px] font-black text-[#284e13] uppercase tracking-widest hover:bg-[#fe9900] hover:text-zinc-950 transition-all active:scale-95">
                                    открыть
                                  </span>
                                </button>
                              );
                            })
                          )}
                        </div>
                      </>
                    ) : null}

                    {inlineUrl ? (
                      <div id="asset-preview-container" className="mt-5 overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-lg animate-in fade-in slide-in-from-top-4 duration-500">
                        <div className="flex items-center justify-between gap-3 border-b border-zinc-200 bg-zinc-50 px-4 py-3">
                          <div className="min-w-0">
                            <div className="text-[9px] font-black uppercase tracking-widest text-zinc-600">ПРЕДПРОСМОТР</div>
                            <div className="mt-1 truncate text-xs font-bold text-zinc-950">{formatAssetTitle(inlineName || "") || inlineName}</div>
                          </div>
                          <button
                            type="button"
                            onClick={closeInline}
                            className="h-9 rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                          >
                            Закрыть
                          </button>
                        </div>
                        {canInlinePreview ? (
                          <div className="overflow-hidden">
                            {inlineKind === "video" ? (
                              <video src={inlineUrl} controls className="w-full h-auto bg-black" preload="metadata" />
                            ) : inlineKind === "audio" ? (
                              <div className="p-4">
                                <audio src={inlineUrl} controls className="w-full" preload="metadata" />
                              </div>
                            ) : inlineKind === "pdf" ? (
                              <div>
                                <div className="flex items-center justify-end gap-2 px-4 pt-4">
                                  <Button
                                    variant="outline"
                                    className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                                    onClick={() => window.open(inlineUrl, "_blank", "noopener,noreferrer")}
                                  >
                                    ОТКРЫТЬ В НОВОЙ ВКЛАДКЕ
                                  </Button>
                                </div>
                                <iframe
                                  src={inlineUrl}
                                  className="w-full h-[420px]"
                                  referrerPolicy="no-referrer"
                                  title={String(inlineName || "PDF")}
                                />
                              </div>
                            ) : inlineKind === "image" ? (
                              <img src={inlineUrl} alt="" className="w-full h-auto" />
                            ) : inlineKind === "text" ? (
                              <div className="p-4">
                                <pre className="whitespace-pre-wrap text-xs leading-relaxed text-zinc-800">{inlineText || ""}</pre>
                              </div>
                            ) : (
                              <iframe
                                src={inlineUrl}
                                className="w-full h-[520px]"
                                sandbox="allow-same-origin allow-scripts allow-forms"
                                title={String(inlineName || "Viewer")}
                              />
                            )}
                          </div>
                        ) : (
                          <div className="p-4">
                            <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600">ПРЕДПРОСМОТР НЕДОСТУПЕН</div>
                            <div className="mt-2 text-[11px] font-bold text-zinc-800">
                              Этот формат не поддерживает предпросмотр в браузере.
                            </div>
                            <div className="mt-4">
                              <button
                                type="button"
                                onClick={() => (inlineUrl ? window.open(inlineUrl, "_blank", "noopener,noreferrer") : null)}
                                className="rounded-xl bg-[#fe9900]/10 border border-[#fe9900]/25 px-3 py-2 text-[9px] font-black text-[#284e13] uppercase tracking-widest hover:bg-[#fe9900] hover:text-zinc-950 transition-all active:scale-95"
                              >
                                Открыть в новом окне
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    ) : null}
                  </div>
                )}
              </CardContent>
            </Card>

            <div className="lg:col-span-2 space-y-6">
              <div className="rounded-[28px] border border-zinc-200 bg-white/70 backdrop-blur-md p-8 shadow-2xl shadow-zinc-950/10">
                <div className="mb-8 flex items-center justify-between">
                  <h2 className="text-xs font-black uppercase tracking-[0.3em] text-zinc-500">Путь обучения</h2>
                </div>

                {outlinePath.length ? (
                  <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-2 text-[10px] font-black uppercase tracking-widest text-zinc-600">
                      <button
                        type="button"
                        onClick={() => setOutlinePath([])}
                        className={
                          "rounded-lg px-2 py-1 transition " +
                          (outlinePath.length === 0 ? "bg-zinc-100 text-zinc-900" : "text-zinc-600 hover:bg-zinc-50")
                        }
                      >
                        /
                      </button>
                      {outlinePath.map((seg: string, idx: number) => (
                        <div key={`bc:${idx}`} className="flex items-center gap-2">
                          <span className="text-zinc-400">/</span>
                          <button
                            type="button"
                            onClick={() => setOutlinePath(outlinePath.slice(0, idx + 1))}
                            className={
                              "rounded-lg px-2 py-1 transition " +
                              (idx === outlinePath.length - 1
                                ? "bg-zinc-100 text-zinc-900"
                                : "text-zinc-600 hover:bg-zinc-50")
                            }
                          >
                            {seg}
                          </button>
                        </div>
                      ))}
                    </div>
                    <button
                      type="button"
                      onClick={() => setOutlinePath(outlinePath.slice(0, -1))}
                      className="h-9 rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                    >
                      Назад
                    </button>
                  </div>
                ) : null}
                {loading ? (
                  <div className="space-y-4">
                    <Skeleton className="h-24 w-full rounded-[24px] bg-zinc-100" />
                    <Skeleton className="h-24 w-full rounded-[24px] bg-zinc-100" />
                  </div>
                ) : submodules.length === 0 ? (
                  (assetBrowser.hasAny ? (
                    <div className="rounded-[24px] border border-zinc-200 bg-white/70 p-8">
                      <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">МОДУЛЬ-МАТЕРИАЛЫ</div>
                      <div className="mt-3 text-2xl font-black tracking-tighter text-zinc-950 uppercase leading-none">
                        Здесь нет уроков — только материалы
                      </div>
                      <div className="mt-4 text-[11px] font-bold text-zinc-600 leading-relaxed">
                        Откройте файлы слева в разделе «Материалы». Прогресс будет засчитан после открытия модуля или любого материала.
                      </div>
                      <div className="mt-6 flex flex-wrap items-center gap-3">
                        <button
                          type="button"
                          onClick={() => {
                            try {
                              const el = document.querySelector('[data-corelms="module-assets-card"]');
                              (el as any)?.scrollIntoView?.({ behavior: "smooth", block: "start" });
                            } catch {
                              // ignore
                            }
                          }}
                          className="h-12 rounded-2xl bg-[#fe9900] px-8 text-[10px] font-black uppercase tracking-widest text-zinc-950 shadow-2xl shadow-[#fe9900]/20 hover:bg-[#f48f00] transition-all active:scale-[0.98]"
                        >
                          ОТКРЫТЬ МАТЕРИАЛЫ
                        </button>
                        {progress?.completed ? (
                          <div className="h-12 inline-flex items-center rounded-2xl border border-[#284e13]/25 bg-[#284e13]/10 px-5 text-[10px] font-black uppercase tracking-widest text-[#284e13]">
                            ЗАСЧИТАНО
                          </div>
                        ) : null}
                      </div>
                    </div>
                  ) : (
                    <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600 py-20 text-center border border-dashed border-zinc-200 rounded-[24px]">
                      Нет уроков
                    </div>
                  ))
                ) : (
                  <div className="relative">
                    <div className="absolute left-[15px] top-2 bottom-2 w-px bg-zinc-200" />
                    <div className="grid gap-4">
                      {outlineFolders.map((name: string) => {
                        const nextPath = outlinePath.concat([name]);
                        const dotClass = "bg-zinc-300";
                        const dot = (
                          <div className="relative z-10 flex justify-center w-8">
                            <div className={`mt-6 h-2.5 w-2.5 rounded-full border border-white transition-all duration-700 ${dotClass}`} />
                          </div>
                        );

                        return (
                          <button
                            key={`dir:${nextPath.join("/")}`}
                            type="button"
                            onClick={() => {
                              setOutlinePath(nextPath);
                            }}
                            className="flex gap-2 group outline-none text-left"
                          >
                            {dot}
                            <div className="relative rounded-[24px] border px-6 py-5 transition-all duration-300 border-zinc-200 bg-white/70 hover:bg-white flex-1 group-hover:scale-[1.01] active:scale-[0.99]">
                              <div className="flex items-start justify-between gap-6">
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center gap-3">
                                    <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-zinc-200 bg-white text-zinc-700">
                                      <Folder className="h-4 w-4" />
                                    </div>
                                    <span className="text-sm font-black text-zinc-600 tabular-nums uppercase">—</span>
                                    <h4 className="min-w-0 text-base font-black text-zinc-950 uppercase tracking-tighter whitespace-normal break-all leading-snug">{name}</h4>
                                  </div>
                                  <div className="mt-4 flex flex-wrap items-center gap-3">
                                    <div className="rounded-lg px-3 py-1 text-[9px] font-black uppercase tracking-widest border bg-zinc-100 border-zinc-200 text-zinc-600">
                                      ПАПКА
                                    </div>
                                  </div>
                                </div>
                                <div className="shrink-0 pt-1">
                                  <div className="flex items-center justify-center w-8 h-8 rounded-full bg-zinc-50 border border-zinc-200 text-zinc-400 text-sm font-black">→</div>
                                </div>
                              </div>
                            </div>
                          </button>
                        );
                      })}

                      {displayedSubmodules.map((s: Submodule) => {
                        const p = progressMap.get(s.id);
                        const requiresQuiz = Boolean((s as any)?.requires_quiz ?? true);
                        const locked = false;
                        const read = Boolean((p as any)?.read);
                        const passed = requiresQuiz ? Boolean((p as any)?.passed) : false;
                        const done = requiresQuiz ? passed : read;
                        const lockedReason = "";
                        const isCurrent = currentSubmoduleId === s.id;
                        const score = displayScore(p);
                        const a0 = !requiresQuiz ? (submodulePrimaryAssetById[String(s.id)] || null) : null;
                        const materialTag = !requiresQuiz ? getMaterialTag(a0 as any) : "";
                        const allowDownload = !requiresQuiz && isTableFile(a0 as any) && String((a0 as any)?.asset_id || "").trim();

                        const dotClass = locked
                          ? "bg-zinc-300"
                          : done
                          ? "bg-[#284e13]"
                          : isCurrent
                          ? "bg-[#fe9900]"
                          : "bg-zinc-400";

                        const itemClass = `relative rounded-[24px] border px-6 py-5 transition-all duration-300 ${
                          locked
                            ? "border-zinc-200 bg-zinc-50 opacity-50 cursor-not-allowed"
                            : isCurrent
                            ? "border-[#fe9900]/40 bg-[#fe9900]/10 scale-[1.01]"
                            : "border-zinc-200 bg-white/70 hover:bg-white"
                        }`;

                        const rowContent = (
                          <div className="flex items-start justify-between gap-6">
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-3">
                                <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-zinc-200 bg-white text-zinc-700">
                                {requiresQuiz ? (
                                  <HelpCircle className="h-4 w-4" />
                                ) : (() => {
                                    const Icon = a0 ? getAssetIcon(a0 as any) : FileText;
                                    return <Icon className="h-4 w-4" />;
                                  })()}
                              </div>
                                <span className="text-sm font-black text-zinc-600 tabular-nums uppercase">
                                  {String(displayedOrderStartsAtZero ? Number((s as any)?.order || 0) + 1 : Number((s as any)?.order || 0)).padStart(2, "0")}
                                </span>
                                <h4 className="min-w-0 text-base font-black text-zinc-950 uppercase tracking-tighter whitespace-normal break-all leading-snug">
                                  {s.title}
                                </h4>
                              </div>
                              {locked && lockedReason ? (
                                <div className="mt-2 text-[9px] font-black uppercase tracking-widest text-zinc-500">
                                  {lockedReason}
                                </div>
                              ) : null}
                              <div className="mt-4 flex flex-wrap items-center gap-3">
                                <div className="flex items-center gap-2">
                                  <div
                                    className={`rounded-lg px-3 py-1 text-[9px] font-black uppercase tracking-widest border transition-all duration-500 ${
                                      read
                                        ? "bg-[#284e13]/10 border-[#284e13]/20 text-[#284e13]"
                                        : "bg-zinc-100 border-zinc-200 text-zinc-600"
                                    }`}
                                  >
                                    ТЕОРИЯ
                                  </div>
                                  {requiresQuiz ? (
                                    <div
                                      className={`flex items-center gap-2 rounded-lg px-3 py-1 text-[9px] font-black uppercase tracking-widest border transition-all duration-500 ${
                                        passed
                                          ? "bg-[#284e13]/10 border-[#284e13]/20 text-[#284e13]"
                                          : hasAttempt(p)
                                          ? "bg-rose-50 border-rose-200 text-rose-700"
                                          : "bg-zinc-100 border-zinc-200 text-zinc-600"
                                      }`}
                                    >
                                      <span>ТЕСТ</span>
                                      <span
                                        className={`tabular-nums ${
                                          passed
                                            ? "text-[#284e13]"
                                            : score !== null
                                            ? "text-rose-700"
                                            : "text-zinc-600"
                                        }`}
                                      >
                                        {typeof score === "number" ? `${score}%` : "—"}
                                      </span>
                                    </div>
                                  ) : (
                                    (a0 ? (
                                      <div className="flex flex-wrap items-center gap-2">
                                        <div className="rounded-lg px-3 py-1 text-[9px] font-black uppercase tracking-widest border bg-zinc-100 border-zinc-200 text-zinc-600">
                                          {materialTag}
                                        </div>
                                        {allowDownload ? (
                                          <button
                                            type="button"
                                            onClick={(e) => {
                                              e.preventDefault();
                                              e.stopPropagation();
                                              void onDownloadAsset(String((a0 as any)?.asset_id || ""));
                                            }}
                                            className="rounded-lg px-3 py-1 text-[9px] font-black uppercase tracking-widest border bg-white border-zinc-200 text-zinc-700 hover:bg-zinc-50"
                                          >
                                            СКАЧАТЬ
                                          </button>
                                        ) : null}
                                      </div>
                                    ) : null)
                                  )}
                                </div>
                              </div>
                            </div>
                            <div className="shrink-0 pt-1">
                              {done ? (
                                <div className="flex items-center justify-center w-8 h-8 rounded-full bg-[#284e13]/10 border border-[#284e13]/20 text-[#284e13] text-sm font-black">✓</div>
                              ) : (
                                <div className="flex items-center justify-center w-8 h-8 rounded-full bg-zinc-50 border border-zinc-200 text-zinc-400 text-sm font-black">—</div>
                              )}
                            </div>
                          </div>
                        );

                        const dot = (
                          <div className="relative z-10 flex justify-center w-8">
                            <div className={`mt-6 h-2.5 w-2.5 rounded-full border border-white transition-all duration-700 ${dotClass}`} />
                          </div>
                        );

                        return (
                          <Link key={s.id} href={`/submodules/${s.id}?module=${encodeURIComponent(moduleId)}`} className="flex gap-2 group outline-none">
                            {dot}
                            <div className={`${itemClass} flex-1 group-hover:scale-[1.01] active:scale-[0.99]`}>{rowContent}</div>
                          </Link>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
                
                {progress?.final_quiz_id && !loading && (
                  <div className="mt-14 space-y-5">
                    <div className="flex items-center gap-5 px-2">
                      <div className="h-px flex-1 bg-zinc-200" />
                      <div className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.3em]">Финальная аттестация</div>
                      <div className="h-px flex-1 bg-zinc-200" />
                    </div>
                    
                    <div className={`relative rounded-3xl border p-8 transition-all duration-700 ${
                      progress.final_passed
                      ? "border-[#284e13]/25 bg-[#284e13]/5 shadow-[0_0_50px_rgba(40,78,19,0.06)]"
                      : finalExamLocked
                      ? "border-zinc-200 bg-zinc-50"
                      : "border-[#fe9900]/25 bg-[#fe9900]/5 shadow-[0_0_50px_rgba(254,153,0,0.06)]"
                    }`}>
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-10">
                        <div className="flex-1">
                          <h3 className="text-2xl font-black text-zinc-950 flex items-center gap-4 uppercase tracking-tighter">
                            {!progress.final_passed && !finalExamLocked && <div className="w-2.5 h-2.5 rounded-full bg-amber-400 animate-ping" />}
                            Итоговый экзамен модуля
                          </h3>
                          <p className="mt-3 text-sm text-zinc-600 max-w-lg leading-relaxed font-medium">
                            Комплексная проверка знаний по всем темам. Результат фиксируется в отчётах и аналитике.
                          </p>
                          {typeof progress.final_best_score === "number" ? (
                            <div className="mt-4">
                              <div className="flex items-center justify-between text-[10px] font-black uppercase tracking-widest text-zinc-600">
                                <span>Результат</span>
                                <span className={`tabular-nums ${progress.final_passed ? "text-[#284e13]" : "text-rose-700"}`}>
                                  {Math.max(0, Math.min(100, Number(progress.final_best_score || 0)))}%
                                </span>
                              </div>
                              <div className="mt-2 h-1 w-full rounded-full bg-zinc-200 overflow-hidden">
                                <div
                                  className={`h-full transition-all duration-700 ${progress.final_passed ? "bg-[#284e13]" : "bg-rose-500"}`}
                                  style={{ width: `${Math.max(0, Math.min(100, Number(progress.final_best_score || 0)))}%` }}
                                />
                              </div>
                            </div>
                          ) : null}
                          {finalExamLocked ? (
                            <div className="mt-4 text-[10px] font-black uppercase tracking-widest text-zinc-500">
                              Сначала пройдите все тесты уроков
                            </div>
                          ) : null}
                        </div>
                        
                        <div className="shrink-0">
                            {finalExamLocked ? (
                              <Button
                                size="lg"
                                disabled
                                className="px-12 h-16 rounded-2xl font-black text-lg uppercase tracking-widest bg-zinc-200 text-zinc-500"
                              >
                                ЗАКРЫТО
                              </Button>
                            ) : (
                              <Link href={`/quizzes/${progress.final_quiz_id}?module=${moduleId}`}>
                                <Button size="lg" className={`px-12 h-16 rounded-2xl font-black text-lg shadow-2xl transition-all hover:scale-[1.03] active:scale-[0.97] uppercase tracking-widest ${progress.final_passed ? "bg-[#284e13] hover:bg-[#21410f] text-white" : "bg-[#fe9900] hover:bg-[#f48f00] text-zinc-950"}`}>
                                  {progress.final_passed ? "Пересдать" : "Начать"}
                                </Button>
                              </Link>
                            )}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
            </div>
          </div>
        )}
      </div>

      <Modal
        open={folderModalOpen}
        onClose={() => setFolderModalOpen(false)}
        title={folderModalTitle || "Каталог"}
        className="max-w-4xl"
      >
        <div className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2 text-[10px] font-black uppercase tracking-widest text-zinc-600">
              <button
                type="button"
                onClick={() => setFolderModalNavPath([])}
                className={
                  "rounded-lg px-2 py-1 transition " +
                  (folderModalNavPath.length === 0 ? "bg-zinc-100 text-zinc-900" : "text-zinc-600 hover:bg-zinc-50")
                }
              >
                /
              </button>
              {folderModalNavPath.map((seg: string, idx: number) => (
                <div key={`fm:${idx}`} className="flex items-center gap-2">
                  <span className="text-zinc-400">/</span>
                  <button
                    type="button"
                    onClick={() => setFolderModalNavPath(folderModalNavPath.slice(0, idx + 1))}
                    className={
                      "rounded-lg px-2 py-1 transition " +
                      (idx === folderModalNavPath.length - 1
                        ? "bg-zinc-100 text-zinc-900"
                        : "text-zinc-600 hover:bg-zinc-50")
                    }
                  >
                    {seg}
                  </button>
                </div>
              ))}
            </div>
            {folderModalNavPath.length ? (
              <button
                type="button"
                onClick={() => setFolderModalNavPath(folderModalNavPath.slice(0, -1))}
                className="h-9 rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
              >
                Назад
              </button>
            ) : null}
          </div>

          {folderModalLoading ? (
            <div className="py-20 flex justify-center">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-[#fe9900] border-t-transparent" />
            </div>
          ) : !folderBrowser.hasAny ? (
            <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600 py-20 text-center border border-dashed border-zinc-200 rounded-[24px]">
              Папка пуста
            </div>
          ) : (
            <div className="grid gap-3">
              {folderBrowser.entries.map((e: any) => {
                if (e.type === "dir") {
                  return (
                    <button
                      key={`fdir:${e.path.join("/")}`}
                      type="button"
                      onClick={() => setFolderModalNavPath(e.path)}
                      className="flex items-center gap-3 rounded-2xl border border-zinc-200 bg-white p-4 hover:bg-zinc-50 transition w-full text-left"
                    >
                      <Folder className="h-4 w-4 text-zinc-500 shrink-0" />
                      <div className="truncate text-sm font-bold text-zinc-950">{e.name}</div>
                    </button>
                  );
                }

                const Icon = getAssetIcon({ original_filename: e.name, mime_type: e.asset.mime_type, object_key: (e.asset as any)?.object_key });
                return (
                  <button
                    key={`ffile:${e.asset.asset_id}`}
                    type="button"
                    onClick={() => openFileFromFolder(e.asset)}
                    className="flex items-center gap-3 rounded-2xl border border-zinc-200 bg-white p-4 hover:bg-zinc-50 transition text-left w-full"
                  >
                    <Icon className="h-4 w-4 text-zinc-500 shrink-0" />
                    <div className="truncate text-sm font-bold text-zinc-950">{formatAssetTitle(e.name) || e.name}</div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </Modal>

      <Modal
        open={fileModalOpen}
        onClose={closeFileModal}
        title={inlineName || "Просмотр файла"}
        className={["pdf"].includes(String(inlineKind || "")) ? "max-w-6xl" : "max-w-4xl"}
      >
        <div className="overflow-hidden rounded-2xl border border-zinc-200 bg-white">
          {!inlineUrl ? (
            <div className="py-20 text-center text-[10px] font-black uppercase tracking-widest text-zinc-600">
              Загрузка…
            </div>
          ) : inlineKind === "video" ? (
            <video src={inlineUrl} controls className="w-full h-auto" autoPlay />
          ) : inlineKind === "audio" ? (
            <div className="p-10">
              <audio src={inlineUrl} controls className="w-full" autoPlay />
            </div>
          ) : inlineKind === "image" ? (
            <img src={inlineUrl} alt="" className="w-full h-auto" />
          ) : inlineKind === "text" ? (
            <div>
              <div className="flex items-center justify-end gap-2 p-4">
                {(() => {
                  const ext = getExtFromNameOrKey(String(inlineName || ""), null);
                  const isTable = ["xls", "xlsx", "csv"].includes(String(ext || "").toLowerCase());
                  const aid = String(inlineAssetId || "").trim();
                  if (!isTable || !aid) return null;
                  return (
                    <Button
                      variant="outline"
                      className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                      onClick={() => void onDownloadAsset(aid)}
                    >
                      СКАЧАТЬ
                    </Button>
                  );
                })()}
              </div>
              <div className="p-6">
                <pre className="whitespace-pre-wrap text-xs leading-relaxed text-zinc-800">{inlineText || ""}</pre>
              </div>
            </div>
          ) : inlineKind === "office" ? (
            <div>
              <div className="flex items-center justify-end gap-2 p-4">
                {(() => {
                  const ext = getExtFromNameOrKey(String(inlineName || ""), null);
                  const isTable = ["xls", "xlsx", "csv"].includes(String(ext || "").toLowerCase());
                  const aid = String(inlineAssetId || "").trim();
                  if (!isTable || !aid) return null;
                  return (
                    <Button
                      variant="outline"
                      className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                      onClick={() => void onDownloadAsset(aid)}
                    >
                      СКАЧАТЬ
                    </Button>
                  );
                })()}
                <Button
                  variant="outline"
                  className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  onClick={() => window.open((inlineRawUrl || inlineUrl) as string, "_blank", "noopener,noreferrer")}
                >
                  ОТКРЫТЬ ФАЙЛ
                </Button>
              </div>
              <iframe
                src={inlineUrl}
                className="w-full h-[640px]"
                referrerPolicy="no-referrer"
                title={String(inlineName || "OFFICE")}
              />
            </div>
          ) : ["pdf"].includes(String(inlineKind || "")) ? (
            <div>
              <div className="flex items-center justify-end gap-2 p-4">
                <Button
                  variant="outline"
                  className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                  onClick={() => window.open(inlineUrl, "_blank", "noopener,noreferrer")}
                >
                  ОТКРЫТЬ В НОВОЙ ВКЛАДКЕ
                </Button>
              </div>
              <iframe
                src={inlineUrl}
                className="w-full h-[520px]"
                referrerPolicy="no-referrer"
                title={String(inlineName || "PDF")}
              />
            </div>
          ) : (
            <div className="p-10 text-[11px] font-bold text-zinc-700">
              Предпросмотр недоступен.
            </div>
          )}
        </div>
      </Modal>
    </AppShell>
  );
}
