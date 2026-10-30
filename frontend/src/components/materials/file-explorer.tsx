"use client";

import { useState, type DragEvent, type ReactNode } from "react";
import { ChevronRight, Folder, FolderOpen, MoveRight } from "lucide-react";
import { MaterialThumb } from "./file-thumb";
import { browseMaterials, fileExtension, formatBytes, formatFileCount, type Material } from "@/lib/materials";

export type FileMeta = { index: number; count: number; path: string[]; searching: boolean };

export const DRAG_MIME = "application/x-corelms-assets";

export function readDraggedIds(event: DragEvent): string[] {
  try {
    const raw = event.dataTransfer.getData(DRAG_MIME);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch { return []; }
}

/**
 * Единый обозреватель материалов: каталоги + файлы.
 * Используется и в обучении, и в редакторе модуля, поэтому структура папок выглядит одинаково.
 * В редакторе файлы можно перетаскивать в папки — как в обычном проводнике.
 */
export function FileExplorer<T extends Material>({ materials, query = "", renderFile, renderFileBar, empty, className, draggable, dragIds, onDropAssets }: {
  materials: T[];
  query?: string;
  renderFile: (asset: T, meta: FileMeta) => ReactNode;
  renderFileBar?: (files: T[]) => ReactNode;
  empty?: ReactNode;
  className?: string;
  draggable?: boolean;
  dragIds?: (asset: T) => string[];
  onDropAssets?: (ids: string[], folder: string[]) => void;
}) {
  const [path, setPath] = useState<string[]>([]);
  const [hover, setHover] = useState<string | null>(null);
  const { folders, files } = browseMaterials(materials, path, query);
  const searching = !!query.trim();
  const canDrop = !!onDropAssets && !!draggable;

  const dropProps = (target: string[]) => canDrop ? {
    onDragOver: (event: DragEvent) => { if (readDraggedIds(event).length) { event.preventDefault(); event.dataTransfer.dropEffect = "move"; setHover(target.join("/")); } },
    onDragLeave: () => setHover(current => current === target.join("/") ? null : current),
    onDrop: (event: DragEvent) => {
      event.preventDefault();
      const ids = readDraggedIds(event);
      setHover(null);
      if (ids.length) onDropAssets?.(ids, target);
    },
  } : {};

  return <div className={className}>
    {!searching && <nav aria-label="Папки материалов" className={`mb-2 flex flex-wrap items-center gap-1 rounded-xl text-xs text-zinc-500 ${hover === "" ? "bg-amber-50 ring-2 ring-amber-300" : ""}`} {...dropProps([])}>
      <button type="button" onClick={() => setPath([])} aria-current={path.length ? undefined : "page"} className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 hover:bg-zinc-100">
        <FolderOpen size={14} className="text-amber-600" />Все файлы<span className="text-zinc-400"> · {formatFileCount(materials.length)}</span>
      </button>
      {path.map((segment, index) => <span key={index} className={`flex items-center gap-1 rounded-lg ${hover === path.slice(0, index + 1).join("/") ? "bg-amber-50 ring-2 ring-amber-300" : ""}`} {...dropProps(path.slice(0, index + 1))}>
        <ChevronRight size={12} className="text-zinc-300" />
        <button type="button" aria-current={index === path.length - 1 ? "page" : undefined} className="max-w-56 truncate rounded-lg px-2 py-1.5 hover:bg-zinc-100" onClick={() => setPath(path.slice(0, index + 1))}>{segment}</button>
      </span>)}
      {canDrop && <span className="ml-2 hidden items-center gap-1 text-[11px] text-zinc-400 sm:flex"><MoveRight size={12} />перетащите файл на папку</span>}
    </nav>}
    <div className="overflow-visible rounded-xl border border-zinc-200 bg-white">
      {renderFileBar?.(files)}
      {folders.map(folder => {
        const target = [...path, folder];
        const key = target.join("/");
        return <button type="button" key={folder} onClick={() => setPath(target)} {...dropProps(target)}
          className={`flex w-full items-center gap-3 border-b border-zinc-100 px-3 py-3 text-left last:border-b-0 sm:px-4 ${hover === key ? "bg-amber-100 ring-2 ring-inset ring-amber-400" : "hover:bg-amber-50/50"}`}>
          <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl border border-amber-100 bg-amber-50 text-amber-600"><Folder size={24} /></span>
          <span className="min-w-0 flex-1 break-words text-sm font-medium text-zinc-800">{folder}</span>
          {hover === key ? <span className="shrink-0 text-xs font-medium text-amber-800">Переместить сюда</span> : <ChevronRight size={16} className="shrink-0 text-zinc-400" />}
        </button>;
      })}
      {files.map((asset, index) => <div
        key={asset.asset_id}
        draggable={draggable && !!onDropAssets}
        onDragStart={event => {
          if (!draggable) return;
          const ids = dragIds ? dragIds(asset) : [asset.asset_id];
          event.dataTransfer.setData(DRAG_MIME, JSON.stringify(ids));
          event.dataTransfer.effectAllowed = "move";
        }}
        className="cursor-grab active:cursor-grabbing"
      >{renderFile(asset, { index, count: files.length, path, searching })}</div>)}
      {!folders.length && !files.length && (empty || <div className="p-9 text-center"><Folder size={28} className="mx-auto mb-3 text-zinc-300" /><p className="text-sm font-medium text-zinc-600">{searching ? "Файлы не найдены" : "Здесь пока нет файлов"}</p><p className="mt-1 text-xs leading-relaxed text-zinc-400">{searching ? "Попробуйте другое название." : "Добавьте материалы — они появятся в этом каталоге."}</p></div>)}
    </div>
  </div>;
}

/** Строка файла: крупное превью, название, тип и размер. */
export function FileRow({ asset, onOpen, openLabel, actions, selected, showFullPath, children, meta }: {
  asset: Material;
  onOpen?: () => void;
  openLabel?: string;
  actions?: ReactNode;
  selected?: boolean;
  showFullPath?: boolean;
  children?: ReactNode;
  meta?: ReactNode;
}) {
  const name = showFullPath ? asset.original_filename : asset.original_filename.split(/[\\/]/).filter(Boolean).at(-1) || asset.original_filename;
  const details = <>{fileExtension(asset.original_filename).toUpperCase() || "Файл"} · {formatBytes(asset.size_bytes)}{asset.version && asset.version > 1 ? ` · v${asset.version}` : ""}</>;
  const body = <>
    <MaterialThumb asset={asset} size="lg" />
    <span className="min-w-0">
      <span className="block break-words text-sm font-medium leading-5 text-zinc-800">{name}</span>
      <span className="mt-0.5 block break-words text-[11px] leading-4 text-zinc-400">{meta || details}</span>
    </span>
  </>;
  return <div className={`flex items-center gap-2 border-b border-zinc-100 px-3 py-2.5 last:rounded-b-xl last:border-b-0 sm:gap-3 sm:px-4 ${selected ? "bg-amber-50/70" : "hover:bg-zinc-50/70"}`}>
    {children}
    {onOpen
      ? <button type="button" aria-label={openLabel} onClick={onOpen} className="flex min-w-0 flex-1 items-center gap-3 text-left">{body}</button>
      : <div className="flex min-w-0 flex-1 items-center gap-3">{body}</div>}
    {actions}
  </div>;
}
