import { Suspense, type ReactNode } from "react";

// Каждый админ-экран самодостаточен и рендерит общую рамку (AdminScreen).
// Suspense нужен из-за клиентских хуков навигации в дочерних страницах.
export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<p role="status" className="p-10 text-center text-sm text-zinc-500">Загружаем раздел администрирования…</p>}>
      {children}
    </Suspense>
  );
}
