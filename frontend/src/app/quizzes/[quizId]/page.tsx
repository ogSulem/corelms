"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ChevronLeft } from "lucide-react";

import { AppShell } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type QuizQuestion = { id: string; prompt: string; type: string };

function formatPromptLines(prompt: string): string[] {
  const normalized = String(prompt || "")
    .replace(/\r\n/g, "\n")
    .replace(/\s+(?=А\))/g, "\n")
    .replace(/\s+(?=Б\))/g, "\n")
    .replace(/\s+(?=В\))/g, "\n")
    .replace(/\s+(?=Г\))/g, "\n")
    .replace(/\s+(?=Д\))/g, "\n");

  return normalized
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);
}

type QuizStart = {
  quiz_id: string;
  attempt_no: number;
  time_limit: number | null;
  questions: QuizQuestion[];
};

type QuizSubmit = {
  quiz_id: string;
  score: number;
  passed: boolean;
  correct: number;
  total: number;
  xp_awarded: number;
};

export default function QuizPage() {
  const params = useParams<{ quizId: string }>();
  const search = useSearchParams();

  const quizId = params.quizId;
  const moduleId = search.get("module") || "";
  const submoduleId = search.get("submodule") || "";
  const view = search.get("view") || "";

  const [quiz, setQuiz] = useState<QuizStart | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<QuizSubmit | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [readConfirmed, setReadConfirmed] = useState<boolean>(false);
  const [autoStarted, setAutoStarted] = useState(false);
  const [moduleProgress, setModuleProgress] = useState<{
    passed: number;
    total: number;
    final_passed?: boolean;
    final_quiz_id?: string | null;
    final_submodule_id?: string | null;
    submodules?: Array<{ submodule_id: string; passed: boolean; best_score: number | null }>;
  } | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setError(null);

        if (moduleId) {
          const prog = await apiFetch<{
            passed: number;
            total: number;
            final_passed?: boolean;
            final_quiz_id?: string | null;
            final_submodule_id?: string | null;
            submodules: Array<{ submodule_id: string; passed: boolean; best_score: number | null }>;
          }>(`/progress/modules/${moduleId}`);
          setModuleProgress(prog);
        }

        if (submoduleId) {
          const rs = await apiFetch<{ read: boolean }>(`/submodules/${submoduleId}/read-status`);
          setReadConfirmed(Boolean(rs.read));
        } else {
          setReadConfirmed(true);
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (msg.includes("confirm reading")) {
          setReadConfirmed(false);
        } else {
          setError("Не удалось загрузить тест.");
        }
      }
    })();
  }, [moduleId, submoduleId]);

  const isFinalQuiz = useMemo(() => {
    if (!moduleProgress?.final_quiz_id) return false;
    return String(moduleProgress.final_quiz_id) === String(quizId);
  }, [moduleProgress, quizId]);

  const finalUnlocked = useMemo(() => {
    if (!isFinalQuiz) return true;
    const subs = moduleProgress?.submodules || [];
    if (!subs.length) return false;
    return subs.every((s) => Boolean(s.passed));
  }, [isFinalQuiz, moduleProgress]);

  useEffect(() => {
    if (!isFinalQuiz || !finalUnlocked || !moduleProgress?.final_submodule_id || autoStarted) return;
    (async () => {
      try {
        setReadConfirmed(true);
        await apiFetch(`/submodules/${moduleProgress.final_submodule_id}/read`, { method: "POST" });
        const data = await apiFetch<QuizStart>(`/quizzes/${quizId}/start`, { method: "POST" });
        setQuiz(data);
        setAutoStarted(true);
      } catch { /* ignore */ }
    })();
  }, [autoStarted, finalUnlocked, isFinalQuiz, moduleProgress, quizId]);

  async function onStartQuiz() {
    if (!isFinalQuiz && !readConfirmed) {
      setError("Сначала откройте теорию урока и подтвердите прочтение.");
      return;
    }
    try {
      setError(null);
      setResult(null);
      setAnswers({});
      const data = await apiFetch<QuizStart>(`/quizzes/${quizId}/start`, { method: "POST" });
      setQuiz(data);
    } catch (e) {
      const anyErr = e as any;
      const msg = e instanceof Error ? e.message : String(e);
      const rid = String(anyErr?.requestId || anyErr?.request_id || "").trim();
      if ((msg || "").toLowerCase().includes("confirm reading")) {
        setError("Сначала подтвердите прочтение теории урока.");
      } else {
        setError((msg || "Не удалось начать тест") + (rid ? ` (код: ${rid})` : ""));
      }
    }
  }

  async function onSubmitQuiz() {
    if (!quiz) return;
    try {
      const payload = {
        answers: quiz.questions.map((q) => ({ question_id: q.id, answer: answers[q.id] || "" })),
      };
      const data = await apiFetch<QuizSubmit>(`/quizzes/${quiz.quiz_id}/submit`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setResult(data);
      const xp = Number((data as any)?.xp_awarded || 0);
      if (xp > 0 && typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("corelms:toast", {
            detail: { title: `+${xp} XP`, description: data.passed ? "Тест пройден" : "Попытка засчитана" },
          })
        );
      }
      if (typeof window !== "undefined") window.dispatchEvent(new Event("corelms:refresh-me"));
    } catch (e) {
      const anyErr = e as any;
      const msg = e instanceof Error ? e.message : String(e);
      const rid = String(anyErr?.requestId || anyErr?.request_id || "").trim();
      setError((msg || "Ошибка при сдаче теста") + (rid ? ` (код: ${rid})` : ""));
    }
  }

  const theoryHref = submoduleId ? `/submodules/${submoduleId}?module=${encodeURIComponent(moduleId)}` : "";

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-6 py-12 lg:py-20">
        <div className="mb-12 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900] mb-2">
              {isFinalQuiz ? "Итоговая аттестация" : "Тест урока"}
            </div>
            <h1 className="text-4xl font-black tracking-tighter text-zinc-950 uppercase leading-none">
              Аттестация знаний
            </h1>
          </div>
          <Link href={moduleId ? `/modules/${moduleId}` : "/modules"}>
            <Button
              variant="ghost"
              size="sm"
              className="rounded-xl font-black uppercase tracking-widest text-[10px]"
            >
              <ChevronLeft className="mr-2 h-4 w-4" />
              назад к модулю
            </Button>
          </Link>
        </div>

        {error && (
          <div className="mb-10 rounded-2xl border border-rose-500/20 bg-rose-500/5 p-4 text-sm text-rose-400 font-bold uppercase tracking-widest text-center">
            {error}
          </div>
        )}

        <div className="grid gap-10 lg:grid-cols-12 items-start">
          <div className="lg:col-span-4 space-y-6 lg:sticky lg:top-24">
            <div className="relative overflow-hidden border border-zinc-200 bg-white/70 backdrop-blur-md rounded-[28px] shadow-2xl shadow-zinc-950/10 p-8">
              <div className="absolute left-0 top-0 h-full w-[2px] bg-gradient-to-b from-[#fe9900]/40 to-transparent" />
              <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500 mb-8">Панель управления</div>
              
              <div className="space-y-6">
                {!quiz ? (
                  <Button
                    className="w-full h-14 rounded-2xl font-black uppercase tracking-widest text-[10px] shadow-sm"
                    onClick={onStartQuiz}
                    disabled={(isFinalQuiz && !finalUnlocked) || (!isFinalQuiz && !readConfirmed)}
                  >
                    {isFinalQuiz && !finalUnlocked
                      ? "Экзамен закрыт"
                      : !isFinalQuiz && !readConfirmed
                      ? "Сначала теория"
                      : "Начать"}
                  </Button>
                ) : (
                  <div className="space-y-6">
                    <div className="flex items-center justify-between text-[10px] font-black uppercase tracking-widest text-zinc-600">
                      <span>Прогресс</span>
                      <span className="tabular-nums text-[#284e13]">
                        {Object.keys(answers).length} / {quiz.questions.length}
                      </span>
                    </div>
                    <div className="h-1 w-full rounded-full bg-zinc-200 overflow-hidden">
                      <div 
                        className="h-full bg-[#fe9900] transition-all duration-500"
                        style={{ width: `${quiz.questions.length ? Math.round((Object.keys(answers).length / quiz.questions.length) * 100) : 0}%` }}
                      />
                    </div>
                    <Button
                      className="w-full h-14 rounded-2xl font-black uppercase tracking-widest text-[10px] shadow-sm"
                      onClick={onSubmitQuiz}
                      disabled={Boolean(result) || Object.keys(answers).length < quiz.questions.length}
                    >
                      {result ? "Сдано" : "Завершить"}
                    </Button>
                  </div>
                )}

                {theoryHref && !isFinalQuiz && (
                  <Link href={theoryHref} className="block w-full">
                    <Button
                      variant="ghost"
                      className="w-full h-14 rounded-2xl font-black uppercase tracking-widest text-[10px]"
                    >
                      <ChevronLeft className="mr-2 h-4 w-4" />
                      К теории
                    </Button>
                  </Link>
                )}
              </div>
            </div>

            {result && (
              <div
                className={`p-8 rounded-[28px] border transition-all duration-500 animate-in fade-in slide-in-from-top-4 ${
                  result.passed ? "border-[#284e13]/20 bg-[#284e13]/5" : "border-rose-500/20 bg-rose-500/5"
                }`}
              >
                <div className="flex items-center justify-between mb-6">
                  <div className="text-[10px] font-black uppercase tracking-[0.2em] text-zinc-500">Результат</div>
                  <div className={`text-3xl font-black tabular-nums ${result.passed ? "text-[#284e13]" : "text-rose-700"}`}>
                    {result.score}%
                  </div>
                </div>
                <div className={`text-[10px] font-black uppercase tracking-[0.3em] mb-4 ${result.passed ? "text-[#284e13]" : "text-rose-700"}`}>
                  {result.passed ? "Зачёт" : "Не зачёт"}
                </div>
                <p className="text-xs text-zinc-500 font-medium leading-relaxed">
                  {result.passed ? "Прекрасный результат. Навыки подтверждены." : "Недостаточно для зачета. Нужно минимум 70%."}
                </p>
              </div>
            )}
          </div>

          <div className="lg:col-span-8">
            {!quiz ? (
              <div className="relative group overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-12 lg:p-20 shadow-2xl shadow-zinc-950/10 text-center">
                <div className="inline-flex items-center gap-3 px-4 py-2 rounded-full bg-[#fe9900]/10 border border-[#fe9900]/20 mb-8">
                  <span className="text-[10px] font-black text-[#fe9900] uppercase tracking-widest">Этап аттестации</span>
                </div>
                <h2 className="text-4xl font-black text-zinc-950 uppercase tracking-tighter leading-none mb-6">
                  Готов к проверке?
                </h2>
                <p className="text-zinc-500 text-lg font-medium max-w-md mx-auto mb-12">
                  Ответь на вопросы модуля, чтобы зафиксировать прогресс и повысить квалификацию.
                </p>
                <div className="flex justify-center">
                  <div className="text-6xl grayscale opacity-20 group-hover:grayscale-0 group-hover:opacity-100 transition-all duration-700">🎯</div>
                </div>
              </div>
            ) : (
              <div className="space-y-10">
                <div className="rounded-[32px] border border-zinc-200 bg-white/70 p-10 lg:p-16 animate-in fade-in zoom-in-95 duration-500 shadow-2xl shadow-zinc-950/10">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-8 mb-16 border-b border-zinc-200 pb-10">
                    <div className="flex flex-col gap-3">
                      <div className="text-[10px] font-black text-[#fe9900] uppercase tracking-[0.3em]">Тестирование</div>
                      <h2 className="text-3xl font-black text-zinc-950 uppercase tracking-tighter leading-none">Вопросы аттестации</h2>
                    </div>
                    <div className="text-right">
                      <div className="text-[10px] font-black text-zinc-500 uppercase tracking-widest">Попытка</div>
                      <div className="text-4xl font-black text-zinc-950 tabular-nums">#{quiz.attempt_no}</div>
                    </div>
                  </div>

                  <div className="space-y-10">
                    {quiz.questions.map((q, idx) => (
                      <div key={q.id} className="group relative overflow-hidden rounded-[28px] bg-white border border-zinc-200 p-8 transition-all duration-300 hover:bg-zinc-50">
                        <div className="flex gap-8">
                          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#fe9900]/10 border border-[#fe9900]/20 text-zinc-950 text-base font-black tabular-nums">
                            {idx + 1}
                          </span>
                          <div className="flex-1">
                            <div className="text-base font-bold text-zinc-950 leading-relaxed tracking-tight mb-6 space-y-2 whitespace-pre-line">
                              {formatPromptLines(q.prompt).map((ln, i) => (
                                <div key={i} className={/^[А-Д]\)/.test(ln) ? "pl-4 text-zinc-700" : ""}>
                                  {ln}
                                </div>
                              ))}
                            </div>
                            <input
                              className="h-12 w-full rounded-2xl bg-white border border-zinc-200 px-6 text-base text-zinc-950 outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all placeholder:text-zinc-400 font-medium"
                              value={answers[q.id] || ""}
                              onChange={(e) => setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
                              placeholder={q.type === "multi" ? "ABC..." : "Ваш ответ..."}
                              disabled={Boolean(result)}
                            />
                            <div className="mt-4 text-[10px] font-black text-zinc-600 uppercase tracking-widest">
                              {q.type === "multi" ? "НЕСКОЛЬКО ВАРИАНТОВ (БУКВЫ, НАПРИМЕР: A,C)" : "ОДИН ВАРИАНТ (БУКВА A/B/C/D)"}
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {result && (
                  <div className="animate-in fade-in slide-in-from-bottom-10 duration-700" />
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
