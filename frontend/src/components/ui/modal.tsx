"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";

let openDialogs = 0;
let previousOverflow = "";

export function Modal({ open, title, onClose, children, footer, className, disableClose }: {
  open: boolean;
  title?: string;
  onClose: () => void;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  disableClose?: boolean;
}) {
  const dialog = React.useRef<HTMLDivElement>(null);
  const closeRef = React.useRef(onClose);
  const disabledRef = React.useRef(disableClose);
  const titleId = React.useId();
  closeRef.current = onClose;
  disabledRef.current = disableClose;

  React.useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    if (openDialogs++ === 0) { previousOverflow = document.body.style.overflow; document.body.style.overflow = "hidden"; }
    const focusable = () => Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]') || [])
      .filter(el => !el.hidden && el.getAttribute("aria-hidden") !== "true");
    const frame = requestAnimationFrame(() => {
      (dialog.current?.querySelector<HTMLElement>("[autofocus]") || focusable()[0] || dialog.current)?.focus();
    });
    const onKey = (event: KeyboardEvent) => {
      const dialogs = document.querySelectorAll("[data-core-dialog]");
      if (dialogs[dialogs.length - 1] !== dialog.current) return;
      if (event.key === "Escape") {
        event.preventDefault();
        if (!disabledRef.current) closeRef.current();
      }
      if (event.key === "Tab") {
        const elements = focusable();
        const first = elements[0], last = elements[elements.length - 1];
        if (!first) { event.preventDefault(); dialog.current?.focus(); }
        else if (event.shiftKey && (document.activeElement === first || !dialog.current?.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || !dialog.current?.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKey);
      if (--openDialogs === 0) document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, [open]);

  if (!open || typeof document === "undefined") return null;
  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-3 sm:p-6" onMouseDown={event => { if (event.target === event.currentTarget && !disableClose) onClose(); }}>
      <div className="pointer-events-none absolute inset-0 bg-zinc-950/35 backdrop-blur-sm" aria-hidden="true" />
      <div ref={dialog} data-core-dialog role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className={cn("relative flex max-h-[calc(100dvh-2rem)] w-full max-w-[min(96vw,980px)] flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl outline-none", className)}>
        <div className="flex shrink-0 items-center justify-between gap-4 border-b border-zinc-200 px-5 py-4 sm:px-7">
          <h2 id={titleId} className="min-w-0 break-words text-base font-semibold text-zinc-900">{title || "Диалог"}</h2>
          <button type="button" disabled={disableClose} aria-label="Закрыть диалог" onClick={onClose} className="shrink-0 rounded-lg p-2 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-800 disabled:opacity-30"><X size={19} /></button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto break-words p-5 sm:p-7">{children}</div>
        {footer && <div className="shrink-0 border-t border-zinc-200 px-5 py-4 sm:px-7">{footer}</div>}
      </div>
    </div>, document.body,
  );
}
