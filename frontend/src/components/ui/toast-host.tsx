 "use client";

import { useEffect, useState } from "react";

export function ToastHost() {
  const [toasts, setToasts] = useState<any[]>([]);

  const onToast = (e: any) => {
    const id = Math.random().toString(36).substring(7);
    const { title, description } = e.detail;
    setToasts((prev) => [...prev, { id, title, description }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3000);
  };

  useEffect(() => {
    window.addEventListener("core:toast", onToast);
    window.addEventListener("corelms:toast", onToast);
    return () => {
      window.removeEventListener("core:toast", onToast);
      window.removeEventListener("corelms:toast", onToast);
    };
  }, []);

  return (
    <div className="fixed bottom-6 right-6 z-[100] flex flex-col gap-3">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="bg-white/90 border border-zinc-200 rounded-2xl p-4 shadow-xl shadow-zinc-950/10 animate-in slide-in-from-right-4"
        >
          <div className="text-sm font-black uppercase tracking-widest text-[#284e13]">{t.title}</div>
          <div className="text-xs text-zinc-600 mt-1">{t.description}</div>
        </div>
      ))}
    </div>
  );
}
