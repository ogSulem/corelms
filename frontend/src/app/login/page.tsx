import { Suspense } from "react";

import { LoginClient } from "@/app/login/login-client";

/**
 * Форма входа использует `useSearchParams` (redirect/reason), поэтому на сервере
 * она отдаётся как заготовка. Без `fallback` на слабой мобильной сети
 * пользователь видел пустой белый экран, пока не догрузится JS, — выглядело как
 * «страница не открылась». Заготовка занимает то же место и сразу объясняет,
 * что происходит.
 */
export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-dvh items-center justify-center px-4 py-8 sm:px-6 sm:py-12">
          <div role="status" aria-live="polite" className="w-full max-w-lg text-center">
            <div className="text-3xl font-black uppercase tracking-tight text-[#284e13]">КАРКАС</div>
            <div className="text-3xl font-black uppercase tracking-tight text-[#fe9900]">ТАЙГИ</div>
            <div className="mx-auto mt-8 h-1.5 w-40 overflow-hidden rounded-full bg-zinc-200">
              <div className="h-full w-1/2 animate-pulse rounded-full bg-[#fe9900]" />
            </div>
            <p className="mt-4 text-xs font-semibold uppercase tracking-widest text-zinc-500">Открываем форму входа…</p>
          </div>
        </main>
      }
    >
      <LoginClient />
    </Suspense>
  );
}
