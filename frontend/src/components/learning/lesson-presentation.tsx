"use client";

import { useId, useState } from "react";
import { BookOpen, FileText, Files } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AssetPreview } from "@/components/materials/asset-preview";
import { MaterialBrowser } from "@/components/materials/material-browser";
import { useActiveTabVisibility } from "@/lib/hooks/use-active-tab-visibility";
import { cn } from "@/lib/cn";
import { type Material } from "@/lib/materials";

export type PresentationLesson = {
  id: string;
  content?: string;
  content_mode?: "manual" | "import";
  presentation_mode?: "auto" | "material" | "text";
  primary_asset_id?: string | null;
};
type View = "material" | "text" | "files";

/** A single focused reading surface, reused in the learner and author preview. */
export function LessonPresentation({ lesson, assets }: { lesson: PresentationLesson; assets: Material[] }) {
  const id = useId();
  const hasText = !!lesson.content?.trim();
  const defaultView: View = lesson.presentation_mode === "text" && hasText ? "text" : assets.length ? "material" : "text";
  const [chosenView, setView] = useState<View>(defaultView);
  const [selected, setSelected] = useState<string | null>(lesson.primary_asset_id || assets[0]?.asset_id || null);
  const active = assets.find(a => a.asset_id === selected) || assets.find(a => a.asset_id === lesson.primary_asset_id) || assets[0];
  const tabs = [
    ...(assets.length ? [{ value: "material" as const, title: "Материал", Icon: FileText }] : []),
    ...(hasText ? [{ value: "text" as const, title: lesson.content_mode === "import" ? "Конспект" : "Текст урока", Icon: BookOpen }] : []),
    ...(assets.length > 1 ? [{ value: "files" as const, title: `Все файлы · ${assets.length}`, Icon: Files }] : []),
  ];
  const view = tabs.some(t => t.value === chosenView) ? chosenView : defaultView;
  const tabsRef = useActiveTabVisibility(view, "[aria-selected='true']");

  return <section aria-label="Содержимое урока" className="min-w-0 space-y-4">
    {tabs.length > 1 && <div ref={tabsRef} role="tablist" aria-label="Представление урока" className="flex gap-1 overflow-x-auto rounded-xl border border-zinc-200 bg-white p-1.5" onKeyDown={event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button"));
      const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
      const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
      event.preventDefault(); buttons[next]?.focus(); buttons[next]?.click();
    }}>{tabs.map(({ value, title, Icon }) => <button key={value} type="button" role="tab" id={`${id}-${value}`} aria-selected={view === value} aria-controls={`${id}-panel`} tabIndex={view === value ? 0 : -1} onClick={() => setView(value)} className={cn("flex shrink-0 items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors", view === value ? "bg-amber-50 text-amber-900" : "text-zinc-500 hover:bg-zinc-50 hover:text-zinc-800")}><Icon size={16} />{title}</button>)}</div>}
    <div id={`${id}-panel`} role={tabs.length > 1 ? "tabpanel" : undefined} aria-labelledby={tabs.length > 1 ? `${id}-${view}` : undefined} className="min-w-0">
      {view === "text" && <article className="rounded-2xl border border-zinc-200 bg-white p-5 sm:p-7">
        {lesson.content_mode === "import" && assets.length > 0 && <p className="mb-5 border-b border-zinc-100 pb-4 text-xs leading-6 text-zinc-500">Это текст, извлечённый при импорте. Таблицы, изображения и оформление смотрите во вкладке «Материал».</p>}
        {hasText ? <div className="learning-prose"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ children, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer">{children}</a>, img: () => <span className="text-zinc-500">[Изображение — см. оригинал материала]</span> }}>{lesson.content}</ReactMarkdown></div> : <p className="text-sm leading-7 text-zinc-500">В этом уроке пока нет текста или файлов.</p>}
      </article>}
      {view === "material" && active && <div className="space-y-3">
        {assets.length > 1 && <label className="flex flex-wrap items-center gap-2 text-xs font-medium text-zinc-500">Открыт материал<select aria-label="Выбрать материал урока" value={active.asset_id} onChange={e => setSelected(e.target.value)} className="min-w-0 max-w-full flex-1 rounded-xl border border-zinc-200 bg-white px-3 py-2.5 text-sm font-normal text-zinc-800 sm:flex-none sm:max-w-lg">{assets.map(a => <option key={a.asset_id} value={a.asset_id}>{a.original_filename}</option>)}</select></label>}
        <AssetPreview asset={active} />
      </div>}
      {view === "files" && <div className="rounded-2xl border border-zinc-200 bg-white p-4 sm:p-6"><MaterialBrowser materials={assets} selectedId={active?.asset_id} onSelect={asset => { setSelected(asset.asset_id); setView("material"); }} /></div>}
    </div>
  </section>;
}
