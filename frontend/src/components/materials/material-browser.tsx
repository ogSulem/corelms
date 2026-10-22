"use client";

import { useMemo, useState } from "react";
import { ChevronRight, Download, File, FileImage, FileSpreadsheet, FileText, FileVideo, Folder, Headphones, Search } from "lucide-react";
import { downloadMaterial, formatBytes, materialKind, type Material } from "@/lib/materials";
import { cn } from "@/lib/cn";

export function MaterialIcon({ name, size = 20 }: { name: string; size?: number }) {
  const kind = materialKind(name);
  const Icon = kind === "table" ? FileSpreadsheet : kind === "image" ? FileImage : kind === "video" ? FileVideo : kind === "audio" ? Headphones : ["document", "pdf", "text"].includes(kind) ? FileText : File;
  return <Icon size={size} aria-hidden="true" />;
}

export function MaterialBrowser({ materials, onSelect, selectedId }: { materials: Material[]; onSelect: (asset: Material) => void; selectedId?: string }) {
  const [query, setQuery] = useState("");
  const [path, setPath] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const entries = useMemo(() => {
    const folders = new Set<string>();
    const files: Material[] = [];
    const needle = query.trim().toLocaleLowerCase("ru");
    for (const asset of materials) {
      const parts = asset.original_filename.replaceAll("\\", "/").split("/").filter(Boolean);
      if (needle) {
        if (asset.original_filename.toLocaleLowerCase("ru").includes(needle)) files.push(asset);
      } else if (path.every((segment, i) => parts[i] === segment)) {
        if (parts.length > path.length + 1) folders.add(parts[path.length]);
        else files.push(asset);
      }
    }
    return { folders: [...folders].sort((a, b) => a.localeCompare(b, "ru", { numeric: true })), files };
  }, [materials, path, query]);

  async function download(asset: Material) {
    setError(null); setDownloading(asset.asset_id);
    try { await downloadMaterial(asset.asset_id); }
    catch (e) { setError(e instanceof Error ? e.message : "Не удалось скачать файл"); }
    finally { setDownloading(null); }
  }

  return <div className="space-y-3">
    <label className="flex items-center gap-2 rounded-xl border border-zinc-200 bg-white px-3 text-zinc-400">
      <Search size={17} /><input aria-label="Поиск материалов" value={query} onChange={e => setQuery(e.target.value)} placeholder="Найти файл по названию…" className="h-11 w-full min-w-0 bg-transparent text-sm text-zinc-800 outline-none placeholder:text-zinc-400" />
    </label>
    {!query && <nav aria-label="Папки материалов" className="flex flex-wrap items-center gap-1 text-xs text-zinc-500">
      <button type="button" onClick={() => setPath([])} className="rounded px-1.5 py-1 hover:bg-zinc-100">Все файлы</button>
      {path.map((segment, i) => <span key={i} className="flex items-center gap-1"><ChevronRight size={12} /><button type="button" className="max-w-48 truncate rounded px-1.5 py-1 hover:bg-zinc-100" onClick={() => setPath(path.slice(0, i + 1))}>{segment}</button></span>)}
    </nav>}
    {error && <p role="alert" className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
      {entries.folders.map(folder => <button type="button" key={folder} onClick={() => setPath([...path, folder])} className="flex w-full items-center gap-3 border-b border-zinc-100 px-4 py-3 text-left hover:bg-amber-50/50">
        <Folder size={21} className="shrink-0 text-amber-600" /><span className="min-w-0 flex-1 break-words text-sm font-medium text-zinc-800">{folder}</span><ChevronRight size={16} className="text-zinc-400" />
      </button>)}
      {entries.files.map(asset => <div key={asset.asset_id} className={cn("flex items-center gap-1 border-b border-zinc-100 last:border-b-0", selectedId === asset.asset_id ? "bg-amber-50" : "hover:bg-zinc-50")}>
        <button type="button" aria-pressed={selectedId === asset.asset_id} onClick={() => onSelect(asset)} className="flex min-w-0 flex-1 items-center gap-3 px-4 py-3 text-left">
          <span className="shrink-0 text-zinc-500"><MaterialIcon name={asset.original_filename} /></span>
          <span className="min-w-0"><span className="block break-words text-sm font-medium text-zinc-800">{query ? asset.original_filename : asset.original_filename.split(/[\\/]/).pop()}</span><span className="mt-0.5 block text-xs text-zinc-500">{formatBytes(asset.size_bytes)}{asset.version && asset.version > 1 ? ` · v${asset.version}` : ""}</span></span>
        </button>
        <button type="button" aria-label={`Скачать ${asset.original_filename}`} title="Скачать оригинал" disabled={downloading === asset.asset_id} onClick={() => void download(asset)} className="mr-2 shrink-0 rounded-lg p-2.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-800 disabled:opacity-40"><Download size={17} /></button>
      </div>)}
      {!entries.files.length && !entries.folders.length && <div className="p-8 text-center text-sm text-zinc-500">{query ? "Ничего не найдено. Попробуйте другое название." : "Здесь пока нет файлов."}</div>}
    </div>
  </div>;
}
