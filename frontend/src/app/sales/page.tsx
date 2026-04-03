"use client";

import { useMemo, useState } from "react";

import { AppShell } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { cn } from "@/lib/cn";
import {
  salesCatalogsTree,
  salesContractsLinks,
  salesLinksTabs,
  salesPhotosTree,
  salesTopLinks,
  type SalesLink,
  type SalesNode,
} from "@/lib/sales-data";

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
  const u = String(url || "").toLowerCase();
  return u.endsWith(".png") || u.endsWith(".jpg") || u.endsWith(".jpeg") || u.endsWith(".webp") || u.endsWith(".gif");
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
        <a
          key={l.url + l.title}
          href={l.url}
          target="_blank"
          rel="noreferrer"
          className="group rounded-2xl border border-zinc-200 bg-white/80 p-4 hover:bg-white transition"
        >
          <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Ссылка</div>
          <div className="mt-1 text-sm font-bold text-zinc-950 break-words">{l.title}</div>
          <div className="mt-2 text-[10px] font-black uppercase tracking-widest text-[#229ED9]">Открыть ↗</div>
        </a>
      ))}
    </div>
  );
}

function SalesExplorer({
  title,
  root,
  open,
  onClose,
  mode,
}: {
  title: string;
  root: SalesNode[];
  open: boolean;
  onClose: () => void;
  mode: "files" | "links";
}) {
  const [path, setPath] = useState<string[]>([]);
  const [preview, setPreview] = useState<{ title: string; url: string } | null>(null);

  const items = useMemo(() => resolveAtPath(root, path), [root, path]);

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

  const openLink = (l: { title: string; url: string }) => {
    if (mode === "files" && isImageUrl(l.url)) {
      setPreview({ title: l.title, url: l.url });
      return;
    }
    window.open(l.url, "_blank", "noopener,noreferrer");
  };

  return (
    <>
      <Modal
        open={open}
        title={title}
        onClose={() => {
          setPath([]);
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

            {mode === "links" ? (
              <LinkBlocks links={links.map((l) => ({ title: l.title, url: l.url }))} />
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {links.map((l) => (
                  <button
                    key={`file:${l.title}:${l.url}`}
                    type="button"
                    onClick={() => openLink(l)}
                    className="group rounded-2xl border border-zinc-200 bg-white/80 p-4 hover:bg-white transition text-left"
                  >
                    <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Файл</div>
                    <div className="mt-1 text-sm font-bold text-zinc-950 break-words">{l.title}</div>
                    <div className="mt-2 text-[10px] font-black uppercase tracking-widest text-[#229ED9]">Открыть ↗</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </Modal>

      <Modal
        open={Boolean(preview)}
        title={preview?.title || ""}
        onClose={() => setPreview(null)}
        footer={
          <div className="flex items-center justify-end gap-2">
            {preview?.url ? (
              <Button
                variant="outline"
                size="sm"
                className="rounded-xl font-black uppercase tracking-widest text-[10px]"
                onClick={() => window.open(String(preview.url), "_blank", "noopener,noreferrer")}
              >
                Открыть ↗
              </Button>
            ) : null}
            <Button
              variant="outline"
              size="sm"
              className="rounded-xl font-black uppercase tracking-widest text-[10px]"
              onClick={() => setPreview(null)}
            >
              Закрыть
            </Button>
          </div>
        }
      >
        {preview?.url ? (
          <div className="overflow-hidden rounded-2xl border border-zinc-200 bg-white">
            <img src={preview.url} alt="" className="w-full h-auto" />
          </div>
        ) : null}
      </Modal>
    </>
  );
}

function LinksTabbedModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<"houses" | "baths" | "other">("houses");
  const [path, setPath] = useState<string[]>([]);

  const currentTab = useMemo(() => salesLinksTabs.find((t) => t.id === tab) || salesLinksTabs[0], [tab]);
  const items = useMemo(() => resolveAtPath(currentTab?.tree || [], path), [currentTab?.tree, path]);
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
      title="Ссылки"
      onClose={() => {
        setPath([]);
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
        {salesLinksTabs.map((t) => (
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

          <LinkBlocks links={links.map((l) => ({ title: l.title, url: l.url }))} />
        </div>
      )}
    </Modal>
  );
}

export default function SalesPage() {
  const [photosOpen, setPhotosOpen] = useState(false);
  const [catalogsOpen, setCatalogsOpen] = useState(false);
  const [contractsOpen, setContractsOpen] = useState(false);
  const [linksOpen, setLinksOpen] = useState(false);

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-6 py-10 lg:py-16">
        <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900] mb-2">Продажи</div>
        <h1 className="text-5xl font-black tracking-tighter text-zinc-950 uppercase leading-none">Материалы</h1>

        <div className="mt-8">
          <div className="flex flex-wrap items-center gap-2 overflow-x-auto pb-1">
            {salesTopLinks.map((l) => (
              <Button
                key={l.url}
                asChild
                variant="outline"
                className="h-10 rounded-full border-zinc-200 bg-white/70 hover:bg-white text-zinc-950 px-4 shrink-0"
              >
                <a href={l.url} target="_blank" rel="noreferrer" className="flex items-center gap-2">
                  <span className="text-[10px] font-black uppercase tracking-widest whitespace-nowrap">{l.title}</span>
                  <span className="text-[11px] font-black text-[#229ED9]">↗</span>
                </a>
              </Button>
            ))}
          </div>
        </div>

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

          <button
            type="button"
            onClick={() => setContractsOpen(true)}
            className="group text-left rounded-[28px] border border-zinc-200 bg-white/70 backdrop-blur-md p-7 shadow-2xl shadow-zinc-950/10 hover:bg-white transition"
          >
            <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">Блок</div>
            <div className="mt-2 text-2xl font-black tracking-tighter text-zinc-950 uppercase">Договора</div>
            <div className="mt-3 text-[10px] font-bold uppercase tracking-widest text-zinc-600">Ссылки →</div>
          </button>

          <button
            type="button"
            onClick={() => setLinksOpen(true)}
            className="group text-left rounded-[28px] border border-zinc-200 bg-white/70 backdrop-blur-md p-7 shadow-2xl shadow-zinc-950/10 hover:bg-white transition"
          >
            <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">Блок</div>
            <div className="mt-2 text-2xl font-black tracking-tighter text-zinc-950 uppercase">Ссылки</div>
            <div className="mt-3 text-[10px] font-bold uppercase tracking-widest text-zinc-600">Вкладки + проводник →</div>
          </button>
        </div>

        <SalesExplorer
          title="Фотографии"
          root={flattenFolderChildren(salesPhotosTree)}
          open={photosOpen}
          onClose={() => setPhotosOpen(false)}
          mode="files"
        />

        <SalesExplorer
          title="Каталоги"
          root={flattenFolderChildren(salesCatalogsTree)}
          open={catalogsOpen}
          onClose={() => setCatalogsOpen(false)}
          mode="files"
        />

        <Modal
          open={contractsOpen}
          title="Договора"
          onClose={() => setContractsOpen(false)}
          footer={
            <div className="flex items-center justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                className="rounded-xl font-black uppercase tracking-widest text-[10px]"
                onClick={() => setContractsOpen(false)}
              >
                Закрыть
              </Button>
            </div>
          }
        >
          <LinkBlocks links={salesContractsLinks} />
        </Modal>

        <LinksTabbedModal open={linksOpen} onClose={() => setLinksOpen(false)} />
      </div>
    </AppShell>
  );
}
