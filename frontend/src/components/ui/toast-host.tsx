"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, X } from "lucide-react";

type Toast = { id: number; title: string; description: string };

export function ToastHost() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(0);
  useEffect(() => {
    const timers = new Set<ReturnType<typeof setTimeout>>();
    const onToast = (event: Event) => {
      const detail = (event as CustomEvent).detail || {};
      const id = ++counter.current;
      setToasts(previous => [...previous.slice(-3), { id, title: String(detail.title || "Готово"), description: String(detail.description || "") }]);
      const timer = setTimeout(() => { setToasts(previous => previous.filter(t => t.id !== id)); timers.delete(timer); }, 5500);
      timers.add(timer);
    };
    window.addEventListener("core:toast", onToast);
    window.addEventListener("corelms:toast", onToast);
    return () => { window.removeEventListener("core:toast", onToast); window.removeEventListener("corelms:toast", onToast); timers.forEach(clearTimeout); };
  }, []);
  return <div aria-live="polite" aria-relevant="additions" className="pointer-events-none fixed bottom-4 right-4 z-[110] flex w-[min(92vw,400px)] flex-col gap-3 sm:bottom-6 sm:right-6">
    {toasts.map(toast => <div key={toast.id} role="status" className="pointer-events-auto flex items-start gap-3 rounded-2xl border border-zinc-200 bg-white p-4 shadow-xl shadow-zinc-950/10"><CheckCircle2 size={20} className="mt-0.5 shrink-0 text-emerald-700" /><div className="min-w-0 flex-1"><p className="text-sm font-semibold text-zinc-900">{toast.title}</p>{toast.description && <p className="mt-1 text-xs leading-relaxed text-zinc-500">{toast.description}</p>}</div><button type="button" aria-label="Закрыть уведомление" onClick={() => setToasts(previous => previous.filter(t => t.id !== toast.id))} className="rounded p-1 text-zinc-400 hover:text-zinc-800"><X size={15} /></button></div>)}
  </div>;
}
