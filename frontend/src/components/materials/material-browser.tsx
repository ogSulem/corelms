"use client";

import { useState } from "react";
import { Download, Loader2, Search } from "lucide-react";
import { FileExplorer, FileRow } from "./file-explorer";
import { downloadMaterial, folderPath, type Material } from "@/lib/materials";

export { MaterialIcon, MaterialThumb } from "./file-thumb";

export function MaterialBrowser({ materials, onSelect, selectedId }: { materials: Material[]; onSelect: (asset: Material) => void; selectedId?: string }) {
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);

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
    {error && <p role="alert" className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}
    <FileExplorer
      materials={materials}
      query={query}
      renderFile={(asset, meta) => <FileRow
        key={asset.asset_id}
        asset={asset}
        onOpen={() => onSelect(asset)}
        openLabel={`Открыть ${asset.original_filename}`}
        selected={selectedId === asset.asset_id}
        showFullPath={meta.searching}
        meta={meta.searching && folderPath(asset.original_filename).length ? <>{folderPath(asset.original_filename).join(" / ")} · {asset.original_filename.split(".").pop()?.toUpperCase()}</> : undefined}
        actions={<button type="button" aria-label={`Скачать ${asset.original_filename}`} title="Скачать оригинал" disabled={downloading === asset.asset_id} onClick={() => void download(asset)} className="shrink-0 rounded-lg p-2.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-800 disabled:opacity-40">
          {downloading === asset.asset_id ? <Loader2 size={17} className="animate-spin" /> : <Download size={17} />}
        </button>}
      />}
      empty={<div className="p-8 text-center text-sm text-zinc-500">{query ? "Ничего не найдено. Попробуйте другое название." : "Здесь пока нет файлов."}</div>}
    />
  </div>;
}
