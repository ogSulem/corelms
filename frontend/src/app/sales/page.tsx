"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { cn } from "@/lib/cn";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/hooks/use-auth";
import {
  type SalesLink,
  type SalesNode,
} from "@/lib/sales-data";

type SalesLinksTab = {
  id: string;
  label: string;
  links: SalesLink[];
};

type SalesLinksBlock =
  | {
      id: string;
      title: string;
      kind: "links";
      links: SalesLink[];
    }
  | {
      id: string;
      title: string;
      kind: "video";
      tabs: SalesLinksTab[];
    };

type SalesLinksPayload = {
  blocks: SalesLinksBlock[];
};

async function fetchSalesLinks(opts?: { bypassCache?: boolean }) {
  const qs = opts?.bypassCache ? "?bypass_cache=true" : "";
  return apiFetch<SalesLinksPayload>(`/sales-links${qs}`);
}

function flattenFolderChildren(nodes: SalesNode[]): SalesNode[] {
  return (nodes || []).slice();
}

function resolveAtPath(nodes: SalesNode[], path: string[]): SalesNode[] {
  let cur: SalesNode[] = nodes || [];
  for (const seg of path) {
    const found = cur.find((n) => n.kind === "folder" && String(n.title) === String(seg));
    if (!found || found.kind !== "folder") return [];
    cur = found.children || [];
  }
  return cur;
}

function isImageUrl(url: string): boolean {
  const raw = String(url || "").trim();
  if (!raw) return false;
  let path = raw;
  try {
    // Presigned URLs include query params; detect by pathname.
    path = new URL(raw).pathname || raw;
  } catch {
    path = raw.split("?")[0] || raw;
  }
  const u = String(path || "").toLowerCase();
  return u.endsWith(".png") || u.endsWith(".jpg") || u.endsWith(".jpeg") || u.endsWith(".webp") || u.endsWith(".gif");
}

type SalesFilesSection = "photos" | "catalogs";

type SalesFilesEntry = {
  kind: "folder" | "file";
  title: string;
  key: string;
  size?: number | null;
  last_modified?: string | null;
};

async function salesFilesList(section: SalesFilesSection, path: string[]) {
  const qs = new URLSearchParams({ section });
  if (path.length) qs.set("path", path.join("/"));
  return apiFetch<{ prefix: string; path: string; entries: SalesFilesEntry[] }>(`/sales-files/list?${qs.toString()}`);
}

async function salesFilesPresignDownload(key: string) {
  const qs = new URLSearchParams({ key });
  return apiFetch<{ url: string }>(`/sales-files/presign-download?${qs.toString()}`);
}

async function salesFilesPresignUpload(args: { section: SalesFilesSection; path: string[]; filename: string; contentType: string }) {
  return apiFetch<{ key: string; upload_url: string }>("/sales-files/presign-upload", {
    method: "POST",
    body: JSON.stringify({
      section: args.section,
      path: args.path.length ? args.path.join("/") : null,
      filename: args.filename,
      content_type: args.contentType,
    }),
  } as any);
}

async function salesFilesMkdir(args: { section: SalesFilesSection; path: string[]; name: string }) {
  return apiFetch<{ ok: boolean }>("/sales-files/mkdir", {
    method: "POST",
    body: JSON.stringify({
      section: args.section,
      path: args.path.length ? args.path.join("/") : null,
      name: args.name,
    }),
  } as any);
}

async function salesFilesDeleteObject(key: string) {
  const qs = new URLSearchParams({ key });
  return apiFetch<{ ok: boolean }>(`/sales-files/object?${qs.toString()}`, {
    method: "DELETE",
  } as any);
}

async function salesFilesDeleteFolder(section: SalesFilesSection, path: string[]) {
  const qs = new URLSearchParams({ section });
  if (path.length) qs.set("path", path.join("/"));
  return apiFetch<{ ok: boolean; deleted: number }>(`/sales-files/folder?${qs.toString()}`, {
    method: "DELETE",
  } as any);
}

function openExternalLink(opts: { url: string; title?: string; source?: string }) {
  const url = String(opts.url || "").trim();
  if (!url) return;
  window.open(url, "_blank", "noopener,noreferrer");
  void apiFetch("/events/external-link", {
    method: "POST",
    body: JSON.stringify({ url, title: opts.title || null, source: opts.source || null }),
  } as any);
}

function LinkBlocks({ links }: { links: SalesLink[] }) {
  if (!links.length) {
    return (
      <div className="rounded-2xl border border-zinc-200 bg-white p-6 text-center">
        <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600">Нет ссылок</div>
      </div>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {links.map((l) => (
        <button
          key={l.url + l.title}
          type="button"
          onClick={() => openExternalLink({ url: l.url, title: l.title, source: "sales" })}
          className="group rounded-2xl border border-zinc-200 bg-white/80 p-4 hover:bg-white transition"
        >
          <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Ссылка</div>
          <div className="mt-1 text-sm font-bold text-zinc-950 break-words">{l.title}</div>
          <div className="mt-2 text-[10px] font-black uppercase tracking-widest text-[#229ED9]">Открыть ↗</div>
        </button>
      ))}
    </div>
  );
}

function SalesExplorer({
  title,
  open,
  onClose,
  mode,
  section,
  editable,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  mode: "files" | "links";
  section?: SalesFilesSection;
  editable?: boolean;
}) {
  const [path, setPath] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [entries, setEntries] = useState<SalesFilesEntry[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const entriesCacheRef = useRef<Map<string, SalesFilesEntry[]>>(new Map());

  const [lightbox, setLightbox] = useState<{
    open: boolean;
    index: number;
    items: Array<{ title: string; key: string; url: string }>;
  }>({ open: false, index: 0, items: [] });

  const folders = useMemo(() => entries.filter((e) => e.kind === "folder"), [entries]);
  const files = useMemo(() => entries.filter((e) => e.kind === "file"), [entries]);

  const breadcrumbs = useMemo(() => {
    if (!path.length) return ["/"];
    return ["/", ...path];
  }, [path]);

  const cacheKey = useMemo(() => {
    if (mode !== "files" || !section) return "";
    return `${section}:${path.join("/")}`;
  }, [mode, section, path]);

  const refresh = async () => {
    if (mode !== "files" || !section) return;
    const cached = cacheKey ? entriesCacheRef.current.get(cacheKey) : null;
    if (cached && cached.length) {
      setEntries(cached);
    }
    setLoading(true);
    try {
      const r = await salesFilesList(section, path);
      const next = r.entries || [];
      setEntries(next);
      if (cacheKey) entriesCacheRef.current.set(cacheKey, next);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    if (mode !== "files" || !section) return;
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mode, section]);

  useEffect(() => {
    if (!open) return;
    if (mode !== "files" || !section) return;
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  useEffect(() => {
    if (!lightbox.open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setLightbox((s) => ({ ...s, open: false }));
        return;
      }
      if (e.key === "ArrowLeft") {
        setLightbox((s) => {
          const n = s.items.length;
          if (!n) return s;
          return { ...s, index: (s.index - 1 + n) % n };
        });
        return;
      }
      if (e.key === "ArrowRight") {
        setLightbox((s) => {
          const n = s.items.length;
          if (!n) return s;
          return { ...s, index: (s.index + 1) % n };
        });
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [lightbox.open]);

  const openLightboxAt = async (startKey: string) => {
    const curFiles = files || [];
    const imageCandidates = curFiles.filter((f) => isImageUrl(String(f.title || "")));
    if (!imageCandidates.length) return;

    setLoading(true);
    try {
      const presigned = await Promise.all(
        imageCandidates.map(async (f) => {
          try {
            const r = await salesFilesPresignDownload(f.key);
            const url = String(r.url || "");
            return { title: f.title, key: f.key, url };
          } catch {
            return { title: f.title, key: f.key, url: "" };
          }
        })
      );
      const items = presigned.filter((x) => String(x.url || "").trim().length);
      if (!items.length) return;
      const idx = Math.max(0, items.findIndex((x) => x.key === startKey));
      setLightbox({ open: true, index: idx >= 0 ? idx : 0, items });
    } finally {
      setLoading(false);
    }
  };

  const openFile = async (f: SalesFilesEntry) => {
    if (!f.key) return;
    if (isImageUrl(String(f.title || ""))) {
      await openLightboxAt(f.key);
      return;
    }
    const r = await salesFilesPresignDownload(f.key);
    const url = String(r.url || "");
    if (!url) return;
    openExternalLink({ url, title: f.title, source: `sales:${title}` });
  };

  const onUploadPick = async (filesList: FileList | null) => {
    if (!editable || mode !== "files" || !section) return;
    const f = filesList && filesList.length ? filesList[0] : null;
    if (!f) return;
    setLoading(true);
    try {
      const presign = await salesFilesPresignUpload({
        section,
        path,
        filename: f.name,
        contentType: f.type || "application/octet-stream",
      });
      await fetch(String(presign.upload_url), {
        method: "PUT",
        headers: {
          "Content-Type": f.type || "application/octet-stream",
        },
        body: f,
      });
      await refresh();
    } finally {
      setLoading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const onMkdir = async () => {
    if (!editable || mode !== "files" || !section) return;
    const name = window.prompt("Название папки");
    if (!name) return;
    setLoading(true);
    try {
      await salesFilesMkdir({ section, path, name });
      await refresh();
    } finally {
      setLoading(false);
    }
  };

  const onDeleteFile = async (f: SalesFilesEntry) => {
    if (!editable || mode !== "files") return;
    if (!window.confirm(`Удалить файл "${f.title}"?`)) return;
    setLoading(true);
    try {
      await salesFilesDeleteObject(f.key);
      await refresh();
    } finally {
      setLoading(false);
    }
  };

  const onDeleteFolder = async (folderName: string) => {
    if (!editable || mode !== "files" || !section) return;
    if (!window.confirm(`Удалить папку "${folderName}" и всё внутри?`)) return;
    setLoading(true);
    try {
      await salesFilesDeleteFolder(section, path.concat([folderName]));
      await refresh();
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Modal
        open={open}
        title={title}
        onClose={() => {
          setPath([]);
          setLightbox({ open: false, index: 0, items: [] });
          onClose();
        }}
        footer={
          <div className="flex items-center justify-between gap-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500 truncate">
              {breadcrumbs.join(" ")}
            </div>
            <div className="flex items-center gap-2">
              {path.length ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-xl font-black uppercase tracking-widest text-[10px]"
                  onClick={() => setPath((p) => p.slice(0, -1))}
                >
                  Назад
                </Button>
              ) : null}
              <Button
                variant="outline"
                size="sm"
                className="rounded-xl font-black uppercase tracking-widest text-[10px]"
                onClick={() => {
                  setPath([]);
                  onClose();
                }}
              >
                Закрыть
              </Button>
            </div>
          </div>
        }
      >
        {mode === "files" && section ? (
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">
              {loading ? "Загрузка..." : ""}
            </div>
            {editable ? (
              <div className="flex items-center gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  onChange={(e) => void onUploadPick(e.target.files)}
                />
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-xl font-black uppercase tracking-widest text-[10px]"
                  onClick={() => fileInputRef.current?.click()}
                >
                  Загрузить
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-xl font-black uppercase tracking-widest text-[10px]"
                  onClick={() => void onMkdir()}
                >
                  Папка
                </Button>
              </div>
            ) : null}
          </div>
        ) : null}

        {mode === "files" && section ? (
          <div className="hidden" />
        ) : null}

        {!folders.length && !files.length && mode === "files" && section ? (
          <div className="rounded-2xl border border-zinc-200 bg-white p-6 text-center">
            <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600">Пусто</div>
          </div>
        ) : mode === "files" && section ? (
          <div className="grid gap-3">
            {folders.map((f) => (
              <div key={`folder:${f.title}`} className="flex items-stretch gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setPath((p) => p.concat([f.title]));
                  }}
                  className="group flex-1 flex items-center justify-between gap-4 rounded-2xl border border-zinc-200 bg-white/80 p-4 hover:bg-white transition text-left"
                >
                  <div className="min-w-0">
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Папка</div>
                    <div className="mt-1 text-sm font-bold text-zinc-950 break-words">{f.title}</div>
                  </div>
                  <div className="shrink-0 text-zinc-400 font-black">→</div>
                </button>
                {editable ? (
                  <Button
                    variant="outline"
                    className="rounded-2xl px-3 font-black uppercase tracking-widest text-[10px]"
                    onClick={() => void onDeleteFolder(f.title)}
                  >
                    Удалить
                  </Button>
                ) : null}
              </div>
            ))}

            <div className="grid gap-3 sm:grid-cols-2">
              {files.map((f) => (
                <div key={`file:${f.title}:${f.key}`} className="flex items-stretch gap-2">
                  <button
                    type="button"
                    onClick={() => void openFile(f)}
                    className="group flex-1 rounded-2xl border border-zinc-200 bg-white/80 p-4 hover:bg-white transition text-left"
                  >
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Файл</div>
                    <div className="mt-1 text-sm font-bold text-zinc-950 break-words">{f.title}</div>
                    <div className="mt-2 text-[10px] font-black uppercase tracking-widest text-[#229ED9]">Открыть ↗</div>
                  </button>
                  {editable ? (
                    <Button
                      variant="outline"
                      className="rounded-2xl px-3 font-black uppercase tracking-widest text-[10px]"
                      onClick={() => void onDeleteFile(f)}
                    >
                      Удалить
                    </Button>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="rounded-2xl border border-zinc-200 bg-white p-6 text-center">
            <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600">Пусто</div>
          </div>
        )}
      </Modal>

      <Modal
        open={Boolean(lightbox.open)}
        title={lightbox.items[lightbox.index]?.title || ""}
        onClose={() => setLightbox((s) => ({ ...s, open: false }))}
        footer={
          <div className="flex items-center justify-between gap-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500 truncate">
              {lightbox.items.length ? `${lightbox.index + 1} / ${lightbox.items.length}` : ""}
            </div>
            <div className="flex items-center gap-2">
              {lightbox.items.length > 1 ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-xl font-black uppercase tracking-widest text-[10px]"
                  onClick={() =>
                    setLightbox((s) => {
                      const n = s.items.length;
                      if (!n) return s;
                      return { ...s, index: (s.index - 1 + n) % n };
                    })
                  }
                >
                  ←
                </Button>
              ) : null}
              {lightbox.items.length > 1 ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-xl font-black uppercase tracking-widest text-[10px]"
                  onClick={() =>
                    setLightbox((s) => {
                      const n = s.items.length;
                      if (!n) return s;
                      return { ...s, index: (s.index + 1) % n };
                    })
                  }
                >
                  →
                </Button>
              ) : null}
              {lightbox.items[lightbox.index]?.url ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-xl font-black uppercase tracking-widest text-[10px]"
                  onClick={() => window.open(String(lightbox.items[lightbox.index]?.url || ""), "_blank", "noopener,noreferrer")}
                >
                  Открыть ↗
                </Button>
              ) : null}
              <Button
                variant="outline"
                size="sm"
                className="rounded-xl font-black uppercase tracking-widest text-[10px]"
                onClick={() => setLightbox((s) => ({ ...s, open: false }))}
              >
                Закрыть
              </Button>
            </div>
          </div>
        }
      >
        {lightbox.items[lightbox.index]?.url ? (
          <div className="overflow-hidden rounded-2xl border border-zinc-200 bg-white">
            <img src={lightbox.items[lightbox.index].url} alt="" className="w-full h-auto" />
          </div>
        ) : null}
      </Modal>
    </>
  );
}

function LinksTabbedModal({ open, onClose, tabs, title }: { open: boolean; onClose: () => void; tabs: SalesLinksTab[]; title: string }) {
  const [tab, setTab] = useState<string>(tabs[0]?.id || "");
  const [path, setPath] = useState<string[]>([]);

  const normalizedTabs = tabs || [];
  useEffect(() => {
    if (!open) return;
    if (!normalizedTabs.length) return;

    // When tabs are loaded async (or changed), ensure we always point to an existing tab.
    const hasCurrent = normalizedTabs.some((t) => t.id === tab);
    if (!hasCurrent) {
      setTab(normalizedTabs[0]?.id || "");
      setPath([]);
    }
  }, [open, normalizedTabs, tab]);

  const currentTab = useMemo(() => normalizedTabs.find((t) => t.id === tab) || normalizedTabs[0], [normalizedTabs, tab]);
  const currentTree = useMemo(() => {
    return (currentTab?.links || []).map((l) => ({ kind: "link", title: l.title, url: l.url }) as SalesNode);
  }, [currentTab]);
  const items = useMemo(() => resolveAtPath(currentTree || [], path), [currentTree, path]);
  const folders = useMemo(
    () => items.filter((n) => n.kind === "folder") as Array<Extract<SalesNode, { kind: "folder" }>>,
    [items]
  );
  const links = useMemo(
    () => items.filter((n) => n.kind === "link") as Array<Extract<SalesNode, { kind: "link" }>>,
    [items]
  );

  const breadcrumbs = useMemo(() => {
    if (!path.length) return ["/"];
    return ["/", ...path];
  }, [path]);

  return (
    <Modal
      open={open}
      title={title}
      onClose={() => {
        setPath([]);
        setTab(normalizedTabs[0]?.id || "");
        onClose();
      }}
      footer={
        <div className="flex items-center justify-between gap-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500 truncate">
            {currentTab?.label || ""} {breadcrumbs.join(" ")}
          </div>
          <div className="flex items-center gap-2">
            {path.length ? (
              <Button
                variant="outline"
                size="sm"
                className="rounded-xl font-black uppercase tracking-widest text-[10px]"
                onClick={() => setPath((p) => p.slice(0, -1))}
              >
                Назад
              </Button>
            ) : null}
            <Button
              variant="outline"
              size="sm"
              className="rounded-xl font-black uppercase tracking-widest text-[10px]"
              onClick={() => {
                setPath([]);
                onClose();
              }}
            >
              Закрыть
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-wrap items-center gap-2 mb-6">
        {normalizedTabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => {
              setTab(t.id);
              setPath([]);
            }}
            className={cn(
              "h-10 rounded-2xl border px-4 text-[10px] font-black uppercase tracking-widest transition",
              tab === t.id
                ? "border-[#fe9900]/35 bg-[#fe9900]/10 text-zinc-950"
                : "border-zinc-200 bg-white/70 text-zinc-700 hover:bg-white"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {!folders.length && !links.length ? (
        <div className="rounded-2xl border border-zinc-200 bg-white p-6 text-center">
          <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600">Пусто</div>
        </div>
      ) : (
        <div className="grid gap-3">
          {folders.map((f) => (
            <button
              key={`folder:${f.title}`}
              type="button"
              onClick={() => setPath((p) => p.concat([f.title]))}
              className="group flex items-center justify-between gap-4 rounded-2xl border border-zinc-200 bg-white/80 p-4 hover:bg-white transition text-left"
            >
              <div className="min-w-0">
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Папка</div>
                <div className="mt-1 text-sm font-bold text-zinc-950 break-words">{f.title}</div>
              </div>
              <div className="shrink-0 text-zinc-400 font-black">→</div>
            </button>
          ))}

          {links.length ? <LinkBlocks links={links.map((l) => ({ title: l.title, url: l.url }))} /> : null}
        </div>
      )}
    </Modal>
  );
}

export default function SalesPage() {
  const { user } = useAuth();
  const canEdit = user?.role === "superadmin";
  const [editMode, setEditMode] = useState(false);
  const [linksLoading, setLinksLoading] = useState(true);
  const [linksData, setLinksData] = useState<SalesLinksPayload>({ blocks: [] });
  const [linksReloadKey, setLinksReloadKey] = useState(0);
  const [photosOpen, setPhotosOpen] = useState(false);
  const [catalogsOpen, setCatalogsOpen] = useState(false);
  const [openBlockId, setOpenBlockId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const data = await fetchSalesLinks({ bypassCache: Boolean(canEdit) });
        if (!alive) return;
        setLinksData({ blocks: data?.blocks || [] });
      } finally {
        if (alive) setLinksLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [canEdit, linksReloadKey]);

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-6 py-10 lg:py-16">
        <div className="flex items-center justify-between gap-4">
          <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900] mb-2">Продажи</div>
          {canEdit ? (
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                className="rounded-xl font-black uppercase tracking-widest text-[10px]"
                onClick={() => {
                  setLinksLoading(true);
                  setLinksReloadKey((x) => x + 1);
                }}
              >
                Обновить ссылки
              </Button>
              <Button
                variant={editMode ? "primary" : "outline"}
                size="sm"
                className="rounded-xl font-black uppercase tracking-widest text-[10px]"
                onClick={() => setEditMode((v) => !v)}
              >
                {editMode ? "Режим редактирования: Вкл" : "Режим редактирования: Выкл"}
              </Button>
            </div>
          ) : null}
        </div>
        <h1 className="text-5xl font-black tracking-tighter text-zinc-950 uppercase leading-none">Материалы</h1>

        {linksData.blocks
          .filter((b) => b.kind === "links" && (b.title || "").trim().length)
          .filter((b) => {
            const t = (b.title || "").toLowerCase();
            return t.includes("тг") || t.includes("помощ");
          })
          .map((b) => (
            <div key={b.id} className="mt-8">
              <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500 mb-2">{b.title}</div>
              <div className="flex flex-nowrap items-center gap-2 overflow-x-auto pb-1">
                {(b.kind === "links" ? b.links : []).length ? (
                  (b.kind === "links" ? b.links : []).map((l) => (
                    <Button
                      key={l.url}
                      variant="outline"
                      className="h-10 rounded-full border-zinc-200 bg-white/70 hover:bg-white text-zinc-950 px-4 shrink-0"
                    >
                      <button type="button" onClick={() => openExternalLink({ url: l.url, title: l.title, source: b.title })} className="flex items-center gap-2">
                        <span className="text-[10px] font-black uppercase tracking-widest whitespace-nowrap">{l.title}</span>
                        <span className="text-[11px] font-black text-[#229ED9]">↗</span>
                      </button>
                    </Button>
                  ))
                ) : (
                  <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">Нет ссылок</div>
                )}
              </div>
            </div>
          ))}

        <div className="mt-10 grid gap-6 lg:grid-cols-4">
          <button
            type="button"
            onClick={() => setPhotosOpen(true)}
            className="group text-left rounded-[28px] border border-zinc-200 bg-white/70 backdrop-blur-md p-7 shadow-2xl shadow-zinc-950/10 hover:bg-white transition"
          >
            <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">Блок</div>
            <div className="mt-2 text-2xl font-black tracking-tighter text-zinc-950 uppercase">Фотографии</div>
            <div className="mt-3 text-[10px] font-bold uppercase tracking-widest text-zinc-600">Открыть проводник →</div>
          </button>

          <button
            type="button"
            onClick={() => setCatalogsOpen(true)}
            className="group text-left rounded-[28px] border border-zinc-200 bg-white/70 backdrop-blur-md p-7 shadow-2xl shadow-zinc-950/10 hover:bg-white transition"
          >
            <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">Блок</div>
            <div className="mt-2 text-2xl font-black tracking-tighter text-zinc-950 uppercase">Каталоги</div>
            <div className="mt-3 text-[10px] font-bold uppercase tracking-widest text-zinc-600">Открыть проводник →</div>
          </button>

          {linksData.blocks
            .filter((b) => {
              const t = (b.title || "").toLowerCase();
              return !(t.includes("тг") || t.includes("помощ"));
            })
            .map((b) => (
              <button
                key={b.id}
                type="button"
                onClick={() => setOpenBlockId(b.id)}
                className="group text-left rounded-[28px] border border-zinc-200 bg-white/70 backdrop-blur-md p-7 shadow-2xl shadow-zinc-950/10 hover:bg-white transition"
              >
                <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">Блок</div>
                <div className="mt-2 text-2xl font-black tracking-tighter text-zinc-950 uppercase">{b.title}</div>
                <div className="mt-3 text-[10px] font-bold uppercase tracking-widest text-zinc-600">Открыть →</div>
              </button>
            ))}
        </div>

        <SalesExplorer title="Фотографии" open={photosOpen} onClose={() => setPhotosOpen(false)} mode="files" section="photos" editable={canEdit && editMode} />

        <SalesExplorer title="Каталоги" open={catalogsOpen} onClose={() => setCatalogsOpen(false)} mode="files" section="catalogs" editable={canEdit && editMode} />

        {(() => {
          const active = linksData.blocks.find((b) => b.id === openBlockId);
          if (!active) return null;
          if (active.kind === "video") {
            return (
              <LinksTabbedModal
                open={Boolean(openBlockId)}
                onClose={() => setOpenBlockId(null)}
                tabs={active.tabs || []}
                title={active.title}
              />
            );
          }
          return (
            <Modal
              open={Boolean(openBlockId)}
              title={active.title}
              onClose={() => setOpenBlockId(null)}
              footer={
                <div className="flex items-center justify-end gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="rounded-xl font-black uppercase tracking-widest text-[10px]"
                    onClick={() => setOpenBlockId(null)}
                  >
                    Закрыть
                  </Button>
                </div>
              }
            >
              <LinkBlocks links={active.links || []} />
            </Modal>
          );
        })()}
      </div>
    </AppShell>
  );
}
