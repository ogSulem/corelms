"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, BookOpen, LineChart, Settings2, ShieldCheck, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function HomePage() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const auth = await fetch("/api/auth/me", { cache: "no-store" });
        const data = auth.ok ? ((await auth.json()) as { authenticated?: boolean }) : null;
        if (data?.authenticated) {
          router.replace("/dashboard");
          return;
        }
      } finally {
        setChecking(false);
      }
    })();
  }, [router]);

  if (checking) return <main className="min-h-screen bg-white" />;

  return (
    <main className="min-h-screen overflow-hidden">
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute top-[-18%] left-[-12%] w-[62%] h-[62%] rounded-full bg-[#fe9900]/12 blur-[160px]" />
        <div className="absolute top-[18%] right-[-18%] w-[56%] h-[56%] rounded-full bg-[#284e13]/10 blur-[160px]" />
        <div className="absolute bottom-[-20%] left-[10%] w-[64%] h-[64%] rounded-full bg-[#fe9900]/8 blur-[170px]" />
      </div>

      <nav className="relative z-50 flex items-center justify-between px-6 py-6 max-w-6xl mx-auto">
        <Link href="/" className="group flex items-center gap-2">
          <svg
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            className="shrink-0 text-[#fe9900] transition-colors duration-200 group-hover:text-[#284e13]"
            aria-hidden="true"
          >
            <path
              d="M20.7 3.3C14.9 3.5 10.6 5.5 8.2 8.8c-2.6 3.6-2.6 8.3 1 11.9 3.6-3.4 6.4-7.5 8-12.1-1.1 4.9-3.4 9.5-6.8 13.2 4.9.6 9.4-1.4 11.6-5.1 2-3.3 1.7-7.7-1.3-13.4Z"
              fill="currentColor"
            />
            <path
              d="M9.6 20.9c.2-4.3 1.4-7.8 3.6-10.7-2.9 2.5-5 6.2-5.7 10.6-.1.5.3 1 .8 1.1.6.1 1.2-.3 1.3-1Z"
              fill="currentColor"
              opacity="0.55"
            />
          </svg>
          <span className="text-xl font-black uppercase tracking-tight text-[#284e13]">КАРКАС</span>
          <span className="text-xl font-black uppercase tracking-tight text-[#fe9900] transition-colors duration-200 group-hover:text-[#284e13]">
            ТАЙГИ
          </span>
        </Link>

        <Link href="/login">
          <Button className="h-11 rounded-xl">Войти</Button>
        </Link>
      </nav>

      <section className="relative z-10 max-w-6xl mx-auto px-6 pb-10 pt-2">
        <div className="relative overflow-hidden rounded-[34px] border border-zinc-200 bg-white/70 backdrop-blur-2xl shadow-2xl shadow-zinc-950/10">
          <div className="absolute inset-0">
            <div className="absolute -top-24 -left-24 h-64 w-64 rounded-full bg-[#fe9900]/14 blur-[70px]" />
            <div className="absolute -bottom-28 -right-24 h-72 w-72 rounded-full bg-[#284e13]/12 blur-[70px]" />
          </div>
          <div className="relative p-8 sm:p-12">
            <div className="flex flex-col gap-10 lg:flex-row lg:items-end lg:justify-between">
              <div className="max-w-2xl">
                <div className="inline-flex items-center gap-2 rounded-full border border-zinc-200 bg-white/70 px-4 py-2 text-[10px] font-black uppercase tracking-[0.32em] text-zinc-700">
                  <Sparkles className="h-4 w-4 text-[#fe9900]" />
                  Корпоративное обучение и аттестация
                </div>
                <h1 className="mt-5 text-4xl sm:text-5xl font-black tracking-tighter text-zinc-950 uppercase leading-[0.95]">
                  КАРКАС ТАЙГИ
                  <br />
                  <span className="text-[#284e13]">LMS</span> для стройки
                </h1>
                <p className="mt-5 text-base sm:text-lg font-medium text-zinc-700 leading-relaxed">
                  Стандартизируй ввод в должность, закрепляй знания тестами и держи под контролем качество обучения.
                  Быстро. Прозрачно. С отчётами.
                </p>

                <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
                  <Link href="/login" className="sm:w-auto">
                    <Button className="h-14 rounded-2xl px-8 w-full sm:w-auto">
                      Войти и начать <ArrowRight className="ml-3 h-4 w-4" />
                    </Button>
                  </Link>
                </div>
              </div>
            </div>

            <div className="mt-10 grid gap-4 sm:grid-cols-3">
              <div className="rounded-[24px] border border-zinc-200 bg-white/60 p-5 backdrop-blur">
                <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-600">Стандарты</div>
                <div className="mt-2 text-sm font-black uppercase tracking-tight text-zinc-950">Единые правила знаний</div>
              </div>
              <div className="rounded-[24px] border border-zinc-200 bg-white/60 p-5 backdrop-blur">
                <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-600">Прозрачность</div>
                <div className="mt-2 text-sm font-black uppercase tracking-tight text-zinc-950">Прогресс виден сразу</div>
              </div>
              <div className="rounded-[24px] border border-zinc-200 bg-white/60 p-5 backdrop-blur">
                <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-600">Скорость</div>
                <div className="mt-2 text-sm font-black uppercase tracking-tight text-zinc-950">Импорт и обновления</div>
              </div>
            </div>
          </div>
        </div>

        <section className="mt-12">
          <div className="flex items-end justify-between gap-6">
            <div>
              <div className="text-[10px] font-black uppercase tracking-[0.32em] text-[#fe9900]">Для сотрудников</div>
              <h2 className="mt-3 text-3xl sm:text-4xl font-black tracking-tighter text-zinc-950 uppercase">
                Быстрое обучение
                <br />
                без лишних действий
              </h2>
              <p className="mt-4 max-w-2xl text-base font-medium text-zinc-700 leading-relaxed">
                Открываешь модуль — проходишь уроки — сдаёшь тесты. Всё на одном экране, без путаницы.
              </p>
            </div>
          </div>

          <div className="mt-8 grid gap-6 lg:grid-cols-12">
            <div className="lg:col-span-7">
              <div className="rounded-[34px] border border-zinc-200 bg-white/75 backdrop-blur-2xl p-8 sm:p-10 shadow-2xl shadow-zinc-950/10">
                <div className="flex items-center gap-3">
                  <BookOpen className="h-6 w-6 text-[#284e13]" />
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-600">Сценарий</div>
                </div>
                <div className="mt-4 text-2xl sm:text-3xl font-black tracking-tighter text-zinc-950 uppercase">
                  «Открыл → изучил → проверил»
                </div>

                <div className="mt-8 grid gap-4">
                  <div className="flex items-start gap-4 rounded-3xl border border-zinc-200 bg-white/70 p-6">
                    <div className="mt-0.5 h-10 w-10 rounded-2xl border border-[#fe9900]/25 bg-[#fe9900]/15 grid place-items-center text-zinc-950 font-black">
                      1
                    </div>
                    <div>
                      <div className="text-sm font-black uppercase tracking-tight text-zinc-950">Выбери модуль</div>
                      <div className="mt-1 text-sm font-medium text-zinc-700">Один список, понятные статусы, мгновенный доступ к урокам.</div>
                    </div>
                  </div>
                  <div className="flex items-start gap-4 rounded-3xl border border-zinc-200 bg-white/70 p-6">
                    <div className="mt-0.5 h-10 w-10 rounded-2xl border border-[#fe9900]/25 bg-[#fe9900]/15 grid place-items-center text-zinc-950 font-black">
                      2
                    </div>
                    <div>
                      <div className="text-sm font-black uppercase tracking-tight text-zinc-950">Пройди урок</div>
                      <div className="mt-1 text-sm font-medium text-zinc-700">Материалы + контрольные вопросы, всё рядом.</div>
                    </div>
                  </div>
                  <div className="flex items-start gap-4 rounded-3xl border border-zinc-200 bg-white/70 p-6">
                    <div className="mt-0.5 h-10 w-10 rounded-2xl border border-[#284e13]/25 bg-[#284e13]/10 grid place-items-center text-[#284e13] font-black">
                      3
                    </div>
                    <div>
                      <div className="text-sm font-black uppercase tracking-tight text-zinc-950">Сдай тест/экзамен</div>
                      <div className="mt-1 text-sm font-medium text-zinc-700">Результат сохраняется и виден руководителю.</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="lg:col-span-5 grid gap-6">
              <div className="rounded-[34px] border border-zinc-200 bg-white/65 backdrop-blur-2xl p-8 shadow-2xl shadow-zinc-950/10">
                <div className="flex items-center gap-3">
                  <LineChart className="h-6 w-6 text-[#284e13]" />
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-600">Прогресс</div>
                </div>
                <div className="mt-4 text-2xl font-black tracking-tighter text-zinc-950 uppercase">Всегда видно, где ты</div>
                <div className="mt-4 text-sm font-medium text-zinc-700 leading-relaxed">
                  Статусы уроков и тестов, движение по модулю, и финальный экзамен — без “угадайки”.
                </div>
                <div className="mt-6 rounded-3xl border border-zinc-200 bg-white/70 p-5">
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-600">Ритм</div>
                  <div className="mt-2 text-sm font-black uppercase tracking-tight text-zinc-950">Понятные шаги без лишнего</div>
                </div>
              </div>

              <div className="rounded-[34px] border border-zinc-200 bg-white/65 backdrop-blur-2xl p-8 shadow-2xl shadow-zinc-950/10">
                <div className="text-[10px] font-black uppercase tracking-[0.32em] text-zinc-600">Формат</div>
                <div className="mt-3 text-2xl font-black tracking-tighter text-zinc-950 uppercase">Теория → тест → экзамен → отчёт</div>
                <div className="mt-4 text-sm font-medium text-zinc-700">Идеально для стандарта знаний на объектах.</div>
              </div>
            </div>
          </div>
        </section>

        <section className="mt-14">
          <div className="flex items-end justify-between gap-6">
            <div>
              <div className="text-[10px] font-black uppercase tracking-[0.32em] text-[#284e13]">Для админов</div>
              <h2 className="mt-3 text-3xl sm:text-4xl font-black tracking-tighter text-zinc-950 uppercase">
                Управление обучением
                <br />
                как продукт
              </h2>
              <p className="mt-4 max-w-2xl text-base font-medium text-zinc-700 leading-relaxed">
                Импортируй модули пакетно, контролируй генерацию тестов, и держи качество обучения на уровне —
                без ручной рутины и без хаоса.
              </p>
            </div>
          </div>

          <div className="mt-8 grid gap-6 lg:grid-cols-12">
            <div className="lg:col-span-7">
              <div className="rounded-[34px] border border-zinc-200 bg-white/75 backdrop-blur-2xl p-8 sm:p-10 shadow-2xl shadow-zinc-950/10">
                <div className="flex items-center gap-3">
                  <Settings2 className="h-6 w-6 text-[#284e13]" />
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-600">Панель администратора</div>
                </div>
                <div className="mt-4 text-2xl sm:text-3xl font-black tracking-tighter text-zinc-950 uppercase">
                  «Импорт → проверка → публикация»
                </div>

                <div className="mt-8 grid gap-4">
                  <div className="flex items-start gap-4 rounded-3xl border border-zinc-200 bg-white/70 p-6">
                    <div className="mt-0.5 h-10 w-10 rounded-2xl border border-[#284e13]/25 bg-[#284e13]/10 grid place-items-center text-[#284e13] font-black">
                      1
                    </div>
                    <div>
                      <div className="text-sm font-black uppercase tracking-tight text-zinc-950">Загрузи модули пачкой</div>
                      <div className="mt-1 text-sm font-medium text-zinc-700">
                        Несколько ZIP = несколько модулей. Сразу видно статус, этапы и историю.
                      </div>
                    </div>
                  </div>
                  <div className="flex items-start gap-4 rounded-3xl border border-zinc-200 bg-white/70 p-6">
                    <div className="mt-0.5 h-10 w-10 rounded-2xl border border-[#fe9900]/25 bg-[#fe9900]/15 grid place-items-center text-zinc-950 font-black">
                      2
                    </div>
                    <div>
                      <div className="text-sm font-black uppercase tracking-tight text-zinc-950">Проверь тесты и вопросы</div>
                      <div className="mt-1 text-sm font-medium text-zinc-700">
                        Редактор вопросов прямо в карточке модуля. Можно быстро поправить качество.
                      </div>
                    </div>
                  </div>
                  <div className="flex items-start gap-4 rounded-3xl border border-zinc-200 bg-white/70 p-6">
                    <div className="mt-0.5 h-10 w-10 rounded-2xl border border-[#284e13]/25 bg-[#284e13]/10 grid place-items-center text-[#284e13] font-black">
                      3
                    </div>
                    <div>
                      <div className="text-sm font-black uppercase tracking-tight text-zinc-950">Публикуй только готовое</div>
                      <div className="mt-1 text-sm font-medium text-zinc-700">
                        Модуль скрыт от сотрудников, пока тесты не готовы. Если нужен реген — помечается автоматически.
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="lg:col-span-5 grid gap-6">
              <div className="rounded-[34px] border border-zinc-200 bg-white/65 backdrop-blur-2xl p-8 shadow-2xl shadow-zinc-950/10">
                <div className="flex items-center gap-3">
                  <ShieldCheck className="h-6 w-6 text-[#284e13]" />
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-600">Контроль качества</div>
                </div>
                <div className="mt-4 text-2xl font-black tracking-tighter text-zinc-950 uppercase">Тесты под стандарты компании</div>
                <div className="mt-4 text-sm font-medium text-zinc-700 leading-relaxed">
                  На каждом уроке — 5 вопросов. Финальный экзамен автоматически собирается из уроков:
                  по 2 вопроса с каждого, каждый раз случайно.
                </div>
                <div className="mt-6 rounded-3xl border border-zinc-200 bg-white/70 p-5">
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-600">Операционка</div>
                  <div className="mt-2 text-sm font-black uppercase tracking-tight text-zinc-950">От импорта до отчёта — в одном месте</div>
                </div>
              </div>

              <div className="rounded-[34px] border border-zinc-200 bg-white/65 backdrop-blur-2xl p-8 shadow-2xl shadow-zinc-950/10">
                <div className="text-[10px] font-black uppercase tracking-[0.32em] text-zinc-600">Готово к внедрению</div>
                <div className="mt-3 text-2xl font-black tracking-tighter text-zinc-950 uppercase">Одна команда — одна система знаний</div>
                <div className="mt-4 text-sm font-medium text-zinc-700">
                  Админ управляет контентом, сотрудник учится, руководитель видит прогресс.
                </div>
              </div>
            </div>
          </div>
        </section>

      </section>
    </main>
  );
}
