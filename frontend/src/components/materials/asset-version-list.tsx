"use client";

import * as React from "react";
import { Loader2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/materials";

export type AssetVersion = { version: number; size_bytes?: number | null; created_at?: string | null };

/**
 * Один список версий файла для всех мест платформы (редактор раздела и файлы продаж),
 * чтобы история версий выглядела и вела себя одинаково.
 */
export function AssetVersionList({
  versions,
  loading,
  current,
  empty,
  hint,
  disabled,
  onRestore,
}: {
  versions: AssetVersion[];
  loading: boolean;
  current?: React.ReactNode;
  empty: string;
  hint?: React.ReactNode;
  disabled?: boolean;
  onRestore: (version: AssetVersion) => void;
}) {
  return (
    <div className="space-y-3">
      {current}
      {loading ? (
        <p role="status" className="flex items-center gap-2 py-4 text-sm text-zinc-500">
          <Loader2 className="animate-spin" size={16} />
          Загружаем историю…
        </p>
      ) : versions.length ? (
        versions.map(version => (
          <div key={version.version} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-zinc-200 p-4">
            <div>
              <p className="text-sm font-medium">Версия {version.version}</p>
              <p className="mt-1 text-xs text-zinc-500">
                {formatBytes(version.size_bytes)}
                {version.created_at ? ` · ${new Date(version.created_at).toLocaleString("ru-RU")}` : ""}
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="gap-2 rounded-xl text-sm font-medium normal-case tracking-normal"
              disabled={disabled}
              onClick={() => onRestore(version)}
            >
              <RotateCcw size={14} />
              Восстановить
            </Button>
          </div>
        ))
      ) : (
        <p className="py-4 text-sm text-zinc-500">{empty}</p>
      )}
      {hint}
    </div>
  );
}
