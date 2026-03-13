"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, BookOpen, LineChart, Settings2, ShieldCheck, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/hooks/use-auth";

export default function HomePage() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const { user, loading: authLoading } = useAuth();

  useEffect(() => {
    if (authLoading) return;
    if (user) {
      router.replace("/dashboard");
      return;
    }
    setChecking(false);
  }, [authLoading, user, router]);

  if (checking) return <main className="min-h-screen bg-white" />;

  return (
    <main className="min-h-screen overflow-hidden bg-white text-zinc-950">
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute top-[-18%] left-[-12%] w-[62%] h-[62%] rounded-full bg-[#fe9900]/25 blur-[180px]" />
        <div className="absolute top-[18%] right-[-18%] w-[56%] h-[56%] rounded-full bg-[#284e13]/18 blur-[180px]" />
        <div className="absolute bottom-[-20%] left-[10%] w-[64%] h-[64%] rounded-full bg-[#fe9900]/15 blur-[190px]" />
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
          <span className="text-xl font-black uppercase tracking-tight text-zinc-950">КАРКАС</span>
          <span className="text-xl font-black uppercase tracking-tight text-[#fe9900] transition-colors duration-200 group-hover:text-zinc-50">
            ТАЙГИ
          </span>
        </Link>

        <Link href="/login">
          <Button className="h-11 rounded-xl bg-zinc-950 text-white hover:bg-zinc-900">Войти</Button>
        </Link>
      </nav>

      <section className="relative z-10 max-w-6xl mx-auto px-6 pb-10 pt-2">
        <div className="relative overflow-hidden rounded-[40px] border border-zinc-200/70 bg-white/70 backdrop-blur-2xl shadow-[0_30px_120px_rgba(24,24,27,0.10)]">
          <div className="absolute inset-0">
            <div className="absolute -top-28 -left-28 h-72 w-72 rounded-full bg-[#fe9900]/22 blur-[110px]" />
            <div className="absolute -bottom-32 -right-28 h-80 w-80 rounded-full bg-[#284e13]/18 blur-[110px]" />
          </div>

          <div className="relative p-8 sm:p-12">
            <div className="grid gap-10 lg:grid-cols-12 lg:items-end">
              <div className="lg:col-span-7">
                <div className="inline-flex items-center gap-2 rounded-full border border-zinc-200/70 bg-white/70 px-4 py-2 text-[10px] font-black uppercase tracking-[0.32em] text-zinc-700">
                  <Sparkles className="h-4 w-4 text-[#fe9900]" />
                  Система управления знаниями
                </div>
                <h1 className="mt-5 text-4xl sm:text-5xl font-black tracking-tighter text-zinc-950 uppercase leading-[0.95]">
                  Каркас Тайги
                  <br />
                  <span className="bg-gradient-to-r from-[#fe9900] to-[#284e13] bg-clip-text text-transparent">единый стандарт</span>
                  <br />
                  обучения и аттестации
                </h1>
                <p className="mt-5 text-base sm:text-lg font-medium text-zinc-700 leading-relaxed">
                  Когда знания в компании оформлены как продукт — обучение становится быстрым,
                  контроль качества прозрачным, а ввод в должность — предсказуемым.
                </p>

                <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
                  <Link href="/login" className="sm:w-auto">
                    <Button className="h-14 rounded-2xl px-8 w-full sm:w-auto bg-zinc-950 text-white hover:bg-zinc-900">
                      Войти <ArrowRight className="ml-3 h-4 w-4" />
                    </Button>
                  </Link>
                </div>

                <div className="mt-10 grid gap-4 sm:grid-cols-3">
                  <div className="rounded-[26px] border border-zinc-200/70 bg-white/70 p-5 backdrop-blur transition-all duration-200 hover:bg-white hover:border-zinc-300 hover:-translate-y-0.5 shadow-sm">
                    <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Результат</div>
                    <div className="mt-2 text-sm font-black uppercase tracking-tight text-zinc-950">Меньше ошибок на объектах</div>
                  </div>
                  <div className="rounded-[26px] border border-zinc-200/70 bg-white/70 p-5 backdrop-blur transition-all duration-200 hover:bg-white hover:border-zinc-300 hover:-translate-y-0.5 shadow-sm">
                    <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Контроль</div>
                    <div className="mt-2 text-sm font-black uppercase tracking-tight text-zinc-950">Прогресс и аудит</div>
                  </div>
                  <div className="rounded-[26px] border border-zinc-200/70 bg-white/70 p-5 backdrop-blur transition-all duration-200 hover:bg-white hover:border-zinc-300 hover:-translate-y-0.5 shadow-sm">
                    <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Скорость</div>
                    <div className="mt-2 text-sm font-black uppercase tracking-tight text-zinc-950">Импорт и обновления</div>
                  </div>
                </div>
              </div>

              <div className="lg:col-span-5">
                <div className="rounded-[34px] border border-zinc-200/70 bg-white/70 backdrop-blur p-7 shadow-[0_30px_120px_rgba(24,24,27,0.10)]">
                  <div className="text-[10px] font-black uppercase tracking-[0.32em] text-zinc-500">Как это ощущается</div>
                  <div className="mt-4 grid gap-3">
                    <div className="rounded-3xl border border-zinc-200/70 bg-white/70 p-5 transition-all duration-200 hover:bg-white hover:border-zinc-300 hover:-translate-y-0.5 shadow-sm">
                      <div className="flex items-center gap-3">
                        <BookOpen className="h-5 w-5 text-[#fe9900]" />
                        <div className="text-[11px] font-black uppercase tracking-widest text-zinc-950">Обучение без путаницы</div>
                      </div>
                      <div className="mt-2 text-sm font-medium text-zinc-700">
                        Модуль → урок → тест. Один путь. Один экран.
                      </div>
                    </div>
                    <div className="rounded-3xl border border-zinc-200/70 bg-white/70 p-5 transition-all duration-200 hover:bg-white hover:border-zinc-300 hover:-translate-y-0.5 shadow-sm">
                      <div className="flex items-center gap-3">
                        <ShieldCheck className="h-5 w-5 text-[#284e13]" />
                        <div className="text-[11px] font-black uppercase tracking-widest text-zinc-950">Качество подтверждается</div>
                      </div>
                      <div className="mt-2 text-sm font-medium text-zinc-700">
                        Вопросы и экзамен фиксируют знания, а не "просмотр".
                      </div>
                    </div>
                    <div className="rounded-3xl border border-zinc-200/70 bg-white/70 p-5 transition-all duration-200 hover:bg-white hover:border-zinc-300 hover:-translate-y-0.5 shadow-sm">
                      <div className="flex items-center gap-3">
                        <LineChart className="h-5 w-5 text-[#284e13]" />
                        <div className="text-[11px] font-black uppercase tracking-widest text-zinc-950">Руководитель видит картину</div>
                      </div>
                      <div className="mt-2 text-sm font-medium text-zinc-700">
                        Без ручных отчётов и переписок.
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-14 h-px w-full bg-gradient-to-r from-transparent via-[#fe9900]/55 to-[#284e13]/55" />

        <section className="mt-14">
          <div className="grid gap-6 lg:grid-cols-12 items-start">
            <div className="lg:col-span-5">
              <div className="text-[10px] font-black uppercase tracking-[0.32em] text-[#284e13]">Для руководства</div>
              <h2 className="mt-3 text-3xl sm:text-4xl font-black tracking-tighter text-zinc-950 uppercase">
                Знания —
                <br />
                управляемый актив
              </h2>
              <p className="mt-4 text-base font-medium text-zinc-700 leading-relaxed">
                Система строится вокруг результата: понятные правила, контроль прохождения,
                прозрачность качества и быстрые изменения без «ручной магии».
              </p>
            </div>
            <div className="lg:col-span-7 grid gap-4 sm:grid-cols-2">
              <div className="rounded-[34px] border border-zinc-200/70 bg-white/70 backdrop-blur-2xl p-8 shadow-[0_30px_120px_rgba(24,24,27,0.10)] transition-all duration-200 hover:bg-white hover:border-zinc-300 hover:-translate-y-0.5">
                <div className="flex items-center gap-3">
                  <Settings2 className="h-6 w-6 text-[#fe9900]" />
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Управляемость</div>
                </div>
                <div className="mt-4 text-xl font-black tracking-tighter text-zinc-950 uppercase">Контент как продукт</div>
                <div className="mt-3 text-sm font-medium text-zinc-700 leading-relaxed">
                  Импорт, контроль качества вопросов, публикация — с предсказуемыми стадиями и историей.
                </div>
              </div>
              <div className="rounded-[34px] border border-zinc-200/70 bg-white/70 backdrop-blur-2xl p-8 shadow-[0_30px_120px_rgba(24,24,27,0.10)] transition-all duration-200 hover:bg-white hover:border-zinc-300 hover:-translate-y-0.5">
                <div className="flex items-center gap-3">
                  <ShieldCheck className="h-6 w-6 text-[#284e13]" />
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Доверие</div>
                </div>
                <div className="mt-4 text-xl font-black tracking-tighter text-zinc-950 uppercase">Аттестация подтверждает</div>
                <div className="mt-3 text-sm font-medium text-zinc-700 leading-relaxed">
                  На урок — вопросы. На модуль — экзамен. Результат фиксируется и доступен для аудита.
                </div>
              </div>
            </div>
          </div>
        </section>

        <div className="mt-14 h-px w-full bg-gradient-to-r from-transparent via-[#fe9900]/45 to-[#284e13]/45" />

        <section className="mt-14">
          <div className="grid gap-6 lg:grid-cols-12 items-start">
            <div className="lg:col-span-7">
              <div className="rounded-[40px] border border-zinc-200/70 bg-white/70 backdrop-blur-2xl p-8 sm:p-10 shadow-[0_30px_120px_rgba(24,24,27,0.10)] transition-all duration-200 hover:bg-white hover:border-zinc-300 hover:-translate-y-0.5">
                <div className="flex items-center gap-3">
                  <BookOpen className="h-6 w-6 text-[#fe9900]" />
                  <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Для сотрудников</div>
                </div>
                <div className="mt-4 text-2xl sm:text-3xl font-black tracking-tighter text-zinc-950 uppercase">
                  «Открыл → прошёл → подтвердил»
                </div>
                <div className="mt-5 grid gap-4">
                  <div className="flex items-start gap-4 rounded-3xl border border-zinc-200/70 bg-white/70 p-6 transition-all duration-200 hover:bg-white hover:border-zinc-300 shadow-sm">
                    <div className="mt-0.5 h-10 w-10 rounded-2xl border border-[#fe9900]/35 bg-[#fe9900]/20 grid place-items-center text-zinc-950 font-black">1</div>
                    <div>
                      <div className="text-sm font-black uppercase tracking-tight text-zinc-950">Учишься по шагам</div>
                      <div className="mt-1 text-sm font-medium text-zinc-700">Без лишних экранов и контекстов.</div>
                    </div>
                  </div>
                  <div className="flex items-start gap-4 rounded-3xl border border-zinc-200/70 bg-white/70 p-6 transition-all duration-200 hover:bg-white hover:border-zinc-300 shadow-sm">
                    <div className="mt-0.5 h-10 w-10 rounded-2xl border border-[#fe9900]/35 bg-[#fe9900]/20 grid place-items-center text-zinc-950 font-black">2</div>
                    <div>
                      <div className="text-sm font-black uppercase tracking-tight text-zinc-950">Сдаёшь тесты</div>
                      <div className="mt-1 text-sm font-medium text-zinc-700">Система фиксирует результат, а не «просмотр».</div>
                    </div>
                  </div>
                  <div className="flex items-start gap-4 rounded-3xl border border-zinc-200/70 bg-white/70 p-6 transition-all duration-200 hover:bg-white hover:border-zinc-300 shadow-sm">
                    <div className="mt-0.5 h-10 w-10 rounded-2xl border border-[#284e13]/35 bg-[#284e13]/14 grid place-items-center text-[#284e13] font-black">
                      3
                    </div>
                    <div>
                      <div className="text-sm font-black uppercase tracking-tight text-zinc-950">Понимаешь, что дальше</div>
                      <div className="mt-1 text-sm font-medium text-zinc-700">Прогресс прозрачен: что пройдено, что впереди.</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="lg:col-span-5 grid gap-6">
              <div className="rounded-[40px] border border-zinc-200/70 bg-white/70 backdrop-blur-2xl p-8 shadow-[0_30px_120px_rgba(24,24,27,0.10)] transition-all duration-200 hover:bg-white hover:border-zinc-300 hover:-translate-y-0.5">
                <div className="text-[10px] font-black uppercase tracking-[0.32em] text-zinc-500">UX принципы</div>
                <div className="mt-3 text-2xl font-black tracking-tighter text-zinc-950 uppercase">Быстро и актуально</div>
                <div className="mt-4 text-sm font-medium text-zinc-700 leading-relaxed">
                  Данные обновляются «умно»: в фоне и по событиям, без лишней нагрузки.
                  Там, где важно — всегда свежо.
                </div>
              </div>

              <div className="rounded-[40px] border border-zinc-200/70 bg-white/70 backdrop-blur-2xl p-8 shadow-[0_30px_120px_rgba(24,24,27,0.10)] transition-all duration-200 hover:bg-white hover:border-zinc-300 hover:-translate-y-0.5">
                <div className="text-[10px] font-black uppercase tracking-[0.32em] text-zinc-500">Вход</div>
                <div className="mt-3 text-2xl font-black tracking-tighter text-zinc-950 uppercase">Готово к работе</div>
                <div className="mt-4 text-sm font-medium text-zinc-700">
                  Достаточно аккаунта. Дальше — система ведёт по сценарию.
                </div>
                <div className="mt-6">
                  <Link href="/login">
                    <Button className="h-12 rounded-2xl px-6 bg-zinc-950 text-white hover:bg-zinc-900">
                      Войти <ArrowRight className="ml-3 h-4 w-4" />
                    </Button>
                  </Link>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="mt-16">
          <div className="rounded-[44px] border border-zinc-200/70 bg-white/70 backdrop-blur-2xl p-10 sm:p-12 shadow-[0_30px_120px_rgba(24,24,27,0.10)]">
            <div className="flex flex-col gap-8 lg:flex-row lg:items-center lg:justify-between">
              <div className="max-w-2xl">
                <div className="text-[10px] font-black uppercase tracking-[0.32em] text-[#fe9900]">КАРКАС ТАЙГИ</div>
                <div className="mt-3 text-3xl sm:text-4xl font-black tracking-tighter text-zinc-950 uppercase leading-tight">
                  Единая система знаний.
                  <br />
                  Единая картина по людям.
                </div>
              </div>
              <div className="flex flex-col gap-3 sm:flex-row">
                <Link href="/login">
                  <Button className="h-14 rounded-2xl px-8 w-full sm:w-auto bg-zinc-950 text-white hover:bg-zinc-900">
                    Войти в систему <ArrowRight className="ml-3 h-4 w-4" />
                  </Button>
                </Link>
              </div>
            </div>
          </div>
        </section>

      </section>
    </main>
  );
}
