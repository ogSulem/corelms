"use client";

import { useState } from "react";
import { File, FileAudio, FileImage, FileSpreadsheet, FileText, FileVideo, Play } from "lucide-react";
import { cn } from "@/lib/cn";
import { materialKind, materialStreamUrl, materialThumbUrl, type Material } from "@/lib/materials";
import { useInView } from "@/lib/hooks/use-in-view";

/** Тот же набор иконок, что и в списках: один файл — один узнаваемый знак. */
export function MaterialIcon({ name, size = 20 }: { name: string; size?: number }) {
  const kind = materialKind(name);
  const Icon = kind === "table" ? FileSpreadsheet : kind === "image" ? FileImage : kind === "video" ? FileVideo
    : kind === "audio" ? FileAudio : ["document", "pdf", "text"].includes(kind) ? FileText : File;
  return <Icon size={size} aria-hidden="true" />;
}

const TILE = {
  sm: { box: "h-9 w-9", icon: 17 },
  md: { box: "h-11 w-11", icon: 20 },
  lg: { box: "h-14 w-14", icon: 24 },
} as const;

type ThumbSize = keyof typeof TILE;

/**
 * Превью файла для списков. Картинки и видео показывают настоящее изображение,
 * остальные форматы — крупную иконку типа. Загрузка ленивая, только для видимых строк.
 */
export function MaterialThumb({ asset, size = "md", className }: { asset: Material; size?: ThumbSize; className?: string }) {
  const [ref, inView] = useInView<HTMLSpanElement>();
  // thumb → (для фото) оригинал → иконка. Видео оригинал в список не тянем.
  const [stage, setStage] = useState<"thumb" | "original" | "icon">("thumb");
  const kind = materialKind(asset.original_filename);
  const { box, icon } = TILE[size];
  const previewable = !!asset.asset_id && (kind === "image" || kind === "video");
  const src = stage === "original" ? materialStreamUrl(asset.asset_id, asset.version) : materialThumbUrl(asset.asset_id, asset.version);
  const showPicture = previewable && inView && stage !== "icon";
  const failed = stage === "icon" && previewable;
  return <span ref={ref} title={failed && kind === "image" ? "Превью не загрузилось — откройте файл, чтобы увидеть причину" : undefined}
    className={cn("relative flex shrink-0 items-center justify-center overflow-hidden rounded-xl border bg-zinc-50 text-zinc-500", failed && kind === "image" ? "border-amber-200 bg-amber-50/60 text-amber-700" : "border-zinc-200", box, className)}>
    {showPicture && <img src={src} alt="" aria-hidden="true" loading="lazy" decoding="async"
      onError={() => setStage(current => (current === "thumb" && kind === "image" ? "original" : "icon"))}
      className="h-full w-full object-cover" />}
    {!showPicture && <MaterialIcon name={asset.original_filename} size={icon} />}
    {kind === "video" && showPicture && <span className="pointer-events-none absolute inset-0 flex items-center justify-center bg-zinc-950/20"><span className="flex h-6 w-6 items-center justify-center rounded-full bg-white/90 text-zinc-900"><Play size={12} fill="currentColor" /></span></span>}
  </span>;
}
