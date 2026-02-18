"use client";

import * as React from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/cn";

export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  className,
}: {
  open: boolean;
  title?: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
}) {
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6">
      <button
        type="button"
        aria-label="Close modal"
        className="absolute inset-0 bg-black/25 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          "relative w-full max-w-[min(96vw,980px)] max-h-[calc(100vh-3rem)] overflow-hidden overflow-x-hidden rounded-[28px] border border-zinc-200 bg-white/90 backdrop-blur-2xl shadow-2xl shadow-zinc-950/10 flex flex-col",
          className
        )}
      >
        <div className="shrink-0 px-8 py-6 border-b border-zinc-200">
          {title ? (
            <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900]">{title}</div>
          ) : null}
        </div>
        <div className="flex-1 min-h-0 overflow-auto overflow-x-hidden px-6 sm:px-8 py-6 sm:py-8 break-words">
          {children}
        </div>
        {footer ? <div className="shrink-0 px-8 py-6 border-t border-zinc-200">{footer}</div> : null}
      </div>
    </div>,
    document.body
  );
}
