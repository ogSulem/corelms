"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, Download, FileText, Loader2, Maximize2, RefreshCw, ShieldCheck, X } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { columnLabel, downloadMaterial, fileExtension, formatBytes, materialKind, materialThumbUrl, type Material } from "@/lib/materials";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { cn } from "@/lib/cn";

type ViewerState = { state: string; source_version: number; mime_type: string | null; error: string | null; can_retry: boolean };

type PreviewData = {
  kind: "table" | "document" | "text";
  sheets?: string[];
  sheet?: number;
  rows?: string[][];
  blocks?: { type: "heading" | "paragraph"; text: string }[];
  text?: string;
  truncated: boolean;
  notice?: string;
};

export function AssetPreview({ asset, onClose, className, embedded = false }: { asset: Material; onClose?: () => void; className?: string; embedded?: boolean }) {
  return <PreviewContent key={`${asset.asset_id}:${asset.version || 1}`} asset={asset} onClose={onClose} className={className} embedded={embedded} />;
}

/**
 * Просмотр материала в модальном окне: не сдвигает список и не теряет место в списке файлов.
 * Внутри — тот же просмотрщик, что и раньше (PDF/видео/картинки/таблицы/текст).
 */
export function AssetPreviewModal({ asset, onClose }: { asset: Material | null; onClose: () => void }) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function download() {
    if (!asset) return;
    setDownloading(true); setError(null);
    try { await downloadMaterial(asset.asset_id); }
    catch (e) { setError(e instanceof Error ? e.message : "Не удалось скачать файл"); }
    finally { setDownloading(false); }
  }
  return <Modal
    open={!!asset}
    title={asset ? asset.original_filename.split(/[\\/]/).filter(Boolean).at(-1) || asset.original_filename : ""}
    onClose={onClose}
    className="max-w-[min(96vw,1180px)]"
    footer={<div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-[11px] text-zinc-500">{asset ? `${formatBytes(asset.size_bytes)} · ${fileExtension(asset.original_filename).toUpperCase() || "файл"}` : ""}</p>
      <div className="flex items-center gap-2">
        <Button variant="ghost" className="gap-2 rounded-xl text-sm font-medium normal-case tracking-normal" onClick={onClose}>Закрыть</Button>
        <Button variant="outline" className="gap-2 rounded-xl text-sm font-medium normal-case tracking-normal" onClick={() => void download()} disabled={downloading}>
          {downloading ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}Скачать оригинал
        </Button>
      </div>
    </div>}
  >
    {error && <p role="alert" className="mb-3 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}
    {asset && <AssetPreview asset={asset} embedded />}
  </Modal>;
}

function PreviewContent({ asset, onClose, className, embedded = false }: { asset: Material; onClose?: () => void; className?: string; embedded?: boolean }) {
  const [data, setData] = useState<PreviewData | null>(null);
  const [sheet, setSheet] = useState(0);
  const [retry, setRetry] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [ready, setReady] = useState(false);
  // Если копия для браузера уже готова, показываем её сразу — без ожидания опроса статуса.
  const [rendition, setRendition] = useState<ViewerState | null>(() => asset.browser_copy && (materialKind(asset.original_filename) === "video" || materialKind(asset.original_filename) === "document")
    ? { state: "ready", source_version: asset.version || 1, mime_type: materialKind(asset.original_filename) === "document" ? "application/pdf" : "video/mp4", error: null, can_retry: false }
    : null);
  const [viewerError, setViewerError] = useState<string | null>(null);
  const [textFallback, setTextFallback] = useState(false);
  const [preparingAgain, setPreparingAgain] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const playback = useRef<{ time: number; paused: boolean } | null>(null);
  const [pdfSupported, setPdfSupported] = useState(true);
  useEffect(() => { setPdfSupported(navigator.pdfViewerEnabled !== false); }, []);
  const originalKind = materialKind(asset.original_filename);
  const needsPreparation = originalKind === "video" || originalKind === "document";
  const copyAvailable = rendition?.state === "ready";
  // Видео показываем прямо из оригинала: браузер сам решает, играть ли MP4/H.264.
  // Копию включаем только после реальной ошибки декодирования — а не заранее,
  // иначе любое видео начиналось с надписи «преобразуется в MP4».
  const [videoFallback, setVideoFallback] = useState(false);
  const copyReady = copyAvailable && !textFallback && (originalKind === "document" || videoFallback);
  const kind = copyReady ? rendition.mime_type === "application/pdf" ? "pdf" : "video" : originalKind;
  const source = `/api/backend/assets/${encodeURIComponent(asset.asset_id)}/stream?variant=${copyReady ? "browser" : "original"}&v=${asset.version || 1}&retry=${retry}`;
  const native = ["pdf", "image", "audio", "video"].includes(kind);
  const showPreparation = originalKind === "document" && !copyReady && !textFallback;
  const pending = !rendition || ["pending", "queued", "processing"].includes(rendition.state);
  const videoPreparing = originalKind === "video" && videoFallback && !copyReady;
  // Для документов копия нужна всегда; для видео — только если браузер не справился.
  const watchPreparation = originalKind === "document" || videoFallback;

  useEffect(() => {
    if (!needsPreparation || !watchPreparation) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let running = false;
    let complete = false;
    const poll = async () => {
      if (running || complete || controller.signal.aborted) return;
      if (document.hidden) { timer = setTimeout(poll, 15000); return; }
      running = true;
      try {
        const next = await apiFetch<ViewerState>(`/assets/${asset.asset_id}/viewer`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (next.state === "ready" && videoRef.current) playback.current = { time: videoRef.current.currentTime, paused: videoRef.current.paused };
        setRendition(next); setViewerError(null);
        complete = !["pending", "queued", "processing"].includes(next.state);
      } catch (e) {
        if (!controller.signal.aborted) setViewerError(e instanceof Error ? e.message : "Не удалось получить статус подготовки");
        complete = true;
      } finally {
        running = false;
        if (!complete && !controller.signal.aborted) timer = setTimeout(poll, 4000);
      }
    };
    const visible = () => { if (!document.hidden) { clearTimeout(timer); void poll(); } };
    document.addEventListener("visibilitychange", visible);
    void poll();
    return () => { controller.abort(); clearTimeout(timer); document.removeEventListener("visibilitychange", visible); };
  }, [asset.asset_id, needsPreparation, watchPreparation, retry]);

  async function retryPreparation() {
    setPreparingAgain(true); setViewerError(null);
    try {
      await apiFetch(`/assets/${asset.asset_id}/viewer/retry`, { method: "POST" });
      setRendition(null); setRetry(n => n + 1);
    } catch (e) { setViewerError(e instanceof Error ? e.message : "Не удалось повторить подготовку"); }
    finally { setPreparingAgain(false); }
  }

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setReady(false);
    setError(null);
    if (showPreparation || videoPreparing || kind === "download") { setLoading(false); return () => controller.abort(); }
    const load = async () => {
      try {
        if (native) {
          // Продлеваем сессию перед запросом файла, но не блокируем показ:
          // иначе одна временная ошибка хранилища оставляла пустое место вместо картинки.
          await apiFetch(`/assets/${asset.asset_id}/presign-download?action=view`, { signal: controller.signal })
            .catch(() => null);
          if (!controller.signal.aborted) setReady(true);
        } else {
          const result = await apiFetch<PreviewData>(`/assets/${asset.asset_id}/preview?sheet=${sheet}`, { signal: controller.signal });
          if (!controller.signal.aborted) setData(result);
        }
      } catch (e) {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Не удалось открыть файл");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => controller.abort();
  }, [asset.asset_id, kind, native, retry, sheet, copyReady, showPreparation, videoPreparing]);

  async function download() {
    setDownloading(true);
    setDownloadError(null);
    try { await downloadMaterial(asset.asset_id); }
    catch (e) { setDownloadError(e instanceof Error ? e.message : "Не удалось скачать файл"); }
    finally { setDownloading(false); }
  }

  /**
   * Браузер не показал файл — выясняем настоящую причину (нет доступа, файл не догрузился,
   * формат не поддержан) и пишем её вместо общего «что-то пошло не так».
   */
  async function explainMediaFailure() {
    let status = 0;
    try {
      const response = await fetch(source, { method: "GET", headers: { Range: "bytes=0-0" }, credentials: "include", cache: "no-store" });
      status = response.status;
      if (response.ok) {
        setError("Файл скачался, но браузер не смог его показать. Скачайте оригинал — он открывается в обычной программе.");
        return;
      }
    } catch { /* сеть недоступна — сообщим об этом ниже */ }
    const hint = status === 401 || status === 403 ? "Сессия истекла. Обновите страницу и войдите снова."
      : status === 404 ? "Файл не найден в хранилище — вероятно, загрузка оборвалась. Загрузите его ещё раз."
      : status === 415 ? "Этот формат нельзя показать в браузере — скачайте оригинал."
      : status === 416 ? "Файл повреждён: хранилище не отдало его содержимое. Загрузите файл заново."
      : status >= 500 ? `Сервис хранения ответил ошибкой ${status}. Повторите через минуту.`
      : status ? `Не удалось открыть файл (код ${status}).`
      : "Нет связи с сервисом хранения. Проверьте сеть и повторите.";
    setError(`${hint} Оригинал всегда можно скачать кнопкой ниже.`);
  }
  const width = data?.rows?.reduce((max, row) => Math.max(max, row.length), 0) || 0;

  return (
    <section aria-label={`Просмотр: ${asset.original_filename}`} className={cn(embedded ? "overflow-hidden" : "overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm", className)}>
      {!embedded && <header className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200 px-4 py-3 sm:px-5">
        <div className="flex min-w-0 flex-[1_1_192px] items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-50 text-amber-700"><FileText size={20} /></div>
          <div className="min-w-0">
            <h3 className="break-words text-sm font-semibold text-zinc-900">{asset.original_filename}</h3>
            <p className="mt-0.5 text-xs text-zinc-500">{fileExtension(asset.original_filename).toUpperCase() || "Файл"} · {formatBytes(asset.size_bytes)}{asset.version && asset.version > 1 ? ` · Версия ${asset.version}` : ""}</p>
          </div>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          {kind === "pdf" && ready && <a href={source} target="_blank" rel="noopener noreferrer" title="Открыть PDF в отдельной вкладке" className="rounded-lg p-2 text-zinc-500 hover:bg-zinc-100"><Maximize2 size={18} /><span className="sr-only">Открыть PDF в отдельной вкладке</span></a>}
          <Button variant="outline" size="sm" className="gap-2 rounded-lg border-zinc-200 text-xs font-medium normal-case tracking-normal" onClick={() => void download()} disabled={downloading}>
            {downloading ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />} Скачать оригинал
          </Button>
          {onClose && <button type="button" onClick={onClose} aria-label="Закрыть предпросмотр" className="rounded-lg p-2 text-zinc-500 hover:bg-zinc-100"><X size={18} /></button>}
        </div>
      </header>}
      {needsPreparation && watchPreparation && <div className={cn("flex flex-wrap items-center justify-between gap-2 border-b px-5 py-3 text-xs leading-6", copyAvailable ? "border-emerald-100 bg-emerald-50/60 text-emerald-800" : "border-amber-100 bg-amber-50/60 text-amber-900")}>
        <p className="min-w-0 flex-1">{copyAvailable ? originalKind === "video" ? "Этот формат не открылся в браузере, поэтому показана совместимая копия MP4. Оригинал не изменён." : "Для браузера подготовлена PDF-копия. Исходный документ не изменён." : viewerError || rendition?.error || (originalKind === "video" ? "Браузер не открыл этот формат. Готовим совместимую копию — оригинал можно скачать уже сейчас." : "Готовится PDF-копия с оформлением документа. Пока доступен оригинал и быстрый просмотр текста.")}</p>
        {copyAvailable && textFallback && <button type="button" className="font-medium underline" onClick={() => setTextFallback(false)}>Открыть PDF-копию</button>}
        {viewerError && <button type="button" className="font-medium underline" onClick={() => setRetry(n => n + 1)}>Обновить статус</button>}
        {!pending && !copyAvailable && rendition?.can_retry && <button type="button" disabled={preparingAgain} className="font-medium underline disabled:opacity-40" onClick={() => void retryPreparation()}>{preparingAgain ? "Запускаем…" : "Повторить подготовку"}</button>}
      </div>}
      {downloadError && <p role="alert" className="border-b border-rose-100 bg-rose-50 px-5 py-3 text-sm text-rose-700">{downloadError}</p>}
      {loading ? (
        <div role="status" className="flex min-h-60 flex-col items-center justify-center gap-3 text-sm text-zinc-500"><Loader2 className="animate-spin text-amber-600" size={25} />Готовим предпросмотр…</div>
      ) : error ? (
        <div role="alert" className="flex min-h-60 flex-col items-center justify-center gap-4 p-8 text-center">
          <AlertCircle size={30} className="text-amber-600" />
          <p className="max-w-lg text-sm leading-relaxed text-zinc-700">{error}</p>
          <div className="flex flex-wrap justify-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setRetry(v => v + 1)} className="gap-2 rounded-lg text-xs font-medium normal-case tracking-normal"><RefreshCw size={15} />Повторить</Button>
            <Button size="sm" onClick={() => void download()} disabled={downloading} className="rounded-lg text-xs font-medium normal-case tracking-normal">Скачать файл</Button>
          </div>
        </div>
      ) : showPreparation ? (
        <div role="status" className="flex min-h-72 flex-col items-center justify-center gap-4 p-6 text-center">
          {pending && !viewerError ? <Loader2 size={30} className="animate-spin text-amber-600" /> : <FileText size={32} className="text-zinc-300" />}
          <h4 className="text-base font-medium text-zinc-800">{pending && !viewerError ? "Подготавливаем материал для браузера" : "Оригинал доступен для скачивания"}</h4>
          <p className="max-w-lg text-sm leading-7 text-zinc-500">Чтобы не потерять таблицы, изображения и разметку, полный документ открывается как PDF. Текстовый просмотр — упрощённый.</p>
          {originalKind === "document" && <Button variant="outline" size="sm" className="rounded-xl text-xs font-medium normal-case tracking-normal" onClick={() => setTextFallback(true)}>Быстрый просмотр текста</Button>}
        </div>
      ) : kind === "download" ? (
        <div className="flex min-h-60 flex-col items-center justify-center gap-3 p-8 text-center">
          <FileText size={36} className="text-zinc-300" />
          <p className="font-medium text-zinc-800">Файл доступен для скачивания</p>
          <p className="max-w-md text-sm leading-relaxed text-zinc-500">У этого формата нет встроенного просмотра. Откройте оригинал в подходящей программе — файл не потерян.</p>
        </div>
      ) : videoPreparing ? (
        <div role="status" className="flex min-h-72 flex-col items-center justify-center gap-4 p-6 text-center">
          {pending && !viewerError ? <Loader2 size={30} className="animate-spin text-amber-600" /> : <FileText size={32} className="text-zinc-300" />}
          <h4 className="text-base font-medium text-zinc-800">{pending && !viewerError ? "Готовим совместимую видеокопию" : "Этот формат не открывается в браузере"}</h4>
          <p className="max-w-lg text-sm leading-7 text-zinc-500">Оригинал сохранён и доступен для скачивания. Копия появится здесь автоматически — страницу можно закрыть и вернуться позже.</p>
          <Button size="sm" onClick={() => void download()} disabled={downloading} className="rounded-lg text-xs font-medium normal-case tracking-normal">Скачать оригинал</Button>
        </div>
      ) : native && ready ? (
        <div className="bg-zinc-50">
          {kind === "pdf" && !pdfSupported && <p className="px-6 py-12 text-center text-sm leading-7 text-zinc-600">Встроенный просмотр PDF в этом браузере недоступен. Скачайте оригинал или откройте файл в отдельной вкладке.</p>}
          {kind === "pdf" && pdfSupported && <iframe key={retry} title={`PDF: ${asset.original_filename}`} src={source} className={cn("w-full border-0", embedded ? "h-[64vh] min-h-[320px]" : "h-[72vh] min-h-[400px]")} />}
          {kind === "image" && <img src={source} alt={asset.original_filename} onError={() => void explainMediaFailure()} className="mx-auto max-h-[72vh] max-w-full bg-white object-contain" />}
          {kind === "video" && <video ref={videoRef} src={source} poster={materialThumbUrl(asset.asset_id, asset.version)} onError={() => {
            const video = videoRef.current;
            if (video) playback.current = { time: video.currentTime, paused: video.paused };
            if (copyAvailable && !videoFallback) { setVideoFallback(true); return; }
            if (!copyAvailable) { setVideoFallback(true); return; }
            void explainMediaFailure();
          }} onLoadedMetadata={() => {
            const video = videoRef.current, saved = playback.current;
            if (video && saved) { video.currentTime = Math.min(saved.time, video.duration || saved.time); if (!saved.paused) void video.play().catch(() => {}); playback.current = null; }
          }} controls playsInline preload="metadata" className="max-h-[72vh] w-full bg-zinc-950"><track kind="captions" /></video>}
          {kind === "audio" && <div className="p-6 sm:p-10"><audio src={source} controls preload="metadata" onError={() => void explainMediaFailure()} className="w-full"><track kind="captions" /></audio></div>}
        </div>
      ) : data?.kind === "table" ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200 bg-zinc-50 px-4 py-3">
            <label className="flex items-center gap-2 text-sm font-medium text-zinc-700">Лист
              <select aria-label="Лист таблицы" value={sheet} onChange={e => setSheet(Number(e.target.value))} className="max-w-[220px] rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-sm">
                {data.sheets?.map((name, index) => <option key={index} value={index}>{name}</option>)}
              </select>
            </label>
            <span className="text-xs text-zinc-500">{data.rows?.length || 0} строк в предпросмотре · Только чтение</span>
          </div>
          {data.rows?.length ? <div className="max-h-[65vh] overflow-auto" tabIndex={0} role="region" aria-label="Содержимое таблицы">
            <table className="w-full border-collapse text-left text-xs">
              <thead className="sticky top-0 z-10 bg-zinc-100 text-zinc-600"><tr><th scope="col" className="w-10 border-b border-r border-zinc-200 px-3 py-2"><span className="sr-only">Строка</span></th>{Array.from({ length: width }, (_, i) => <th scope="col" key={i} className="min-w-28 border-b border-r border-zinc-200 px-3 py-2 text-center font-medium">{columnLabel(i)}</th>)}</tr></thead>
              <tbody>{data.rows.map((row, i) => <tr key={i} className="even:bg-zinc-50/60 hover:bg-amber-50/50"><th scope="row" className="sticky left-0 border-b border-r border-zinc-200 bg-zinc-100 px-3 py-2 text-right font-normal text-zinc-500">{i + 1}</th>{row.map((cell, j) => <td key={j} title={cell} className={cn("max-w-md whitespace-pre-wrap break-words border-b border-r border-zinc-100 px-3 py-2 align-top leading-relaxed", cell.startsWith("=") && "font-mono text-emerald-800")}>{cell}</td>)}</tr>)}</tbody>
            </table>
          </div> : <p className="p-10 text-center text-sm text-zinc-500">Этот лист пуст.</p>}
        </>
      ) : data?.kind === "document" ? (
        <article className="max-h-[70vh] space-y-3 overflow-auto p-5 text-sm leading-7 text-zinc-800 sm:p-8">
          {data.blocks?.length ? data.blocks.map((block, i) => block.type === "heading" ? <h4 key={i} className="border-b border-zinc-100 pb-2 pt-4 text-lg font-semibold">{block.text}</h4> : <p key={i} className="whitespace-pre-wrap">{block.text}</p>) : <p className="text-zinc-500">Текст не найден. Документ может состоять из изображений — скачайте оригинал.</p>}
        </article>
      ) : data?.kind === "text" ? <pre className="max-h-[65vh] overflow-auto whitespace-pre-wrap break-words p-5 font-mono text-sm leading-6 text-zinc-800">{data.text || "Файл не содержит текста."}</pre> : null}
      {!loading && !error && (data?.notice || data?.truncated) && <div className="space-y-1 border-t border-zinc-200 bg-amber-50/50 px-5 py-3 text-xs leading-relaxed text-zinc-600">
        {data.notice && <p>{data.notice}</p>}
        {data.truncated && <p className="font-medium text-amber-800">Показана часть документа: до 500 строк и 60 столбцов таблицы или ограниченный объём текста. Полная версия — в оригинале.</p>}
      </div>}
      <footer className="flex items-center gap-2 border-t border-zinc-100 px-5 py-2 text-[11px] text-zinc-500"><ShieldCheck size={13} />Файл не передаётся внешним сервисам просмотра</footer>
    </section>
  );
}
