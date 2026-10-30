"use client";

import { useState } from "react";
import { File, FileAudio, FileImage, FileSpreadsheet, FileText, FileVideo, Play } from "lucide-react";
import { cn } from "@/lib/cn";
import { materialKind, materialThumbUrl, type Material } from "@/lib/materials";
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
  const [failed, setFailed] = useState(false);
  const kind = materialKind(asset.original_filename);
  const { box, icon } = TILE[size];
  const canPreview = !failed && !!asset.asset_id && (kind === "image" || kind === "video");
  // Файл не отдался браузеру — показываем иконку с подсказкой, а не пустой серый квадрат.
  const broken = failed && !!asset.asset_id && (kind === "image" || kind === "video");
  // Для видео и документов предпочитаем готовую копию: оригинал (например, H.265 .mp4)
  // браузер не декодирует, и вместо кадра был бы чёрный прямоугольник.
  const src = materialThumbUrl(asset.asset_id, asset.version, !!asset.browser_copy);
  return <span ref={ref} title={broken ? "Превью не загрузилось — откройте файл, чтобы увидеть причину" : undefined}
    className={cn("relative flex shrink-0 items-center justify-center overflow-hidden rounded-xl border bg-zinc-50 text-zinc-500", broken ? "border-amber-200 bg-amber-50/60 text-amber-700" : "border-zinc-200", box, className)}>
    {canPreview && inView && kind === "image" && <img src={src} alt="" aria-hidden="true" loading="lazy" decoding="async" onError={() => setFailed(true)} className="h-full w-full object-cover" />}
    {canPreview && inView && kind === "video" && <>
      <video src={`${src}#t=0.1`} preload="auto" muted playsInline aria-hidden="true" onError={() => setFailed(true)} className="h-full w-full object-cover" />
      <span className="pointer-events-none absolute inset-0 flex items-center justify-center bg-zinc-950/25"><span className="flex h-6 w-6 items-center justify-center rounded-full bg-white/90 text-zinc-900"><Play size={12} fill="currentColor" /></span></span>
    </>}
    {!(canPreview && inView) && <MaterialIcon name={asset.original_filename} size={icon} />}
  </span>;
}
