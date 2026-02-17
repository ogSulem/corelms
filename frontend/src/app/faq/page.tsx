"use client";

import { useMemo, useState } from "react";

import { AppShell } from "@/components/app/shell";

type FaqItem = {
  q: string;
  a: string;
};

export default function FaqPage() {
  const items = useMemo<FaqItem[]>(
    () => [
      {
        q: "Что такое FAQ?",
        a: "FAQ — это страница с ответами на частые вопросы. Здесь будет краткая база знаний по работе с системой, импортам, тестам и ролям.",
      },
      {
        q: "Как импортировать модуль?",
        a: "Открой админ‑панель → Модули → Импорт. Выбери ZIP(ы) и нажми «Запустить». Если модуль помечен «НЕОБХОДИМ РЕГЕН», запусти регенерацию тестов.",
      },
      {
        q: "Почему модуль может требовать регена?",
        a: "Если AI не смог сгенерировать качественные вопросы, система применяет безопасный fallback и помечает вопросы как needs_regen. Такой модуль не публикуется для сотрудников до успешной регенерации.",
      },
      {
        q: "Куда обращаться за доступами?",
        a: "Попроси администратора компании создать пользователя и выдать временный пароль. При первом входе потребуется смена пароля.",
      },
    ],
    []
  );

  const [openIndex, setOpenIndex] = useState<number | null>(0);

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-5xl px-4 py-12">
        <div className="relative overflow-hidden rounded-[36px] border border-zinc-200 bg-white/70 backdrop-blur-md p-10 shadow-2xl shadow-zinc-950/10">
          <div className="absolute -top-24 -right-24 h-64 w-64 rounded-full bg-[#fe9900]/10 blur-2xl" />
          <div className="absolute -bottom-24 -left-24 h-64 w-64 rounded-full bg-[#284e13]/10 blur-2xl" />

          <div className="relative">
            <div className="text-[10px] font-black uppercase tracking-[0.35em] text-[#fe9900]">СПРАВКА</div>
            <h1 className="mt-3 text-4xl font-black tracking-tighter text-zinc-950 uppercase">FAQ</h1>
            <p className="mt-4 text-sm font-bold text-zinc-600 max-w-2xl">
              Частые вопросы по работе с «Каркас Тайги». Страница будет расширяться: инструкции, политика доступа и стандарты качества тестов.
            </p>

            <div className="mt-10 space-y-4">
              {items.map((it, idx) => {
                const open = openIndex === idx;
                return (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => setOpenIndex((prev) => (prev === idx ? null : idx))}
                    className={
                      "w-full text-left group relative overflow-hidden rounded-[22px] border transition-all " +
                      (open
                        ? "border-[#fe9900]/35 bg-white shadow-lg shadow-zinc-950/5"
                        : "border-zinc-200 bg-white/60 hover:bg-white")
                    }
                  >
                    <div className="flex items-start justify-between gap-6 p-6">
                      <div className="min-w-0">
                        <div className="text-xs font-black uppercase tracking-widest text-zinc-950">
                          {it.q}
                        </div>
                        <div
                          className={
                            "mt-3 text-sm font-bold text-zinc-600 leading-relaxed transition-all " +
                            (open ? "max-h-[220px] opacity-100" : "max-h-0 opacity-0")
                          }
                          style={{ overflow: "hidden" }}
                        >
                          {it.a}
                        </div>
                      </div>

                      <div
                        className={
                          "shrink-0 h-10 w-10 rounded-xl border grid place-items-center transition-all " +
                          (open
                            ? "border-[#fe9900]/35 bg-[#fe9900]/10 text-zinc-900"
                            : "border-zinc-200 bg-white text-zinc-600 group-hover:bg-zinc-50")
                        }
                        aria-hidden="true"
                      >
                        <svg
                          width="18"
                          height="18"
                          viewBox="0 0 24 24"
                          fill="none"
                          xmlns="http://www.w3.org/2000/svg"
                          className={"transition-transform " + (open ? "rotate-180" : "rotate-0")}
                        >
                          <path
                            d="M6 9l6 6 6-6"
                            stroke="currentColor"
                            strokeWidth="2.4"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>

            <div className="mt-10 text-[10px] font-black uppercase tracking-[0.35em] text-zinc-500">
              Если не нашёл ответ — напиши администратору компании.
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
