"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Check, CheckCircle2, Clock3, GraduationCap, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { AppShell } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useAuth } from "@/lib/hooks/use-auth";

type Question = { id: string; prompt: string; type: string };
type Quiz = { quiz_id: string; session_id: string; started_at: number; attempt_no: number; attempts_limit: number | null; time_limit: number | null; pass_threshold: number; questions: Question[] };
type QuizContext = { module_id: string; module_title: string; submodule_id: string | null; title: string; current_quiz_id: string; is_final: boolean; can_start: boolean; can_resume?: boolean; start_blocked_reason?: string | null; attempts_remaining?: number | null; attempts_used?: number; passed: boolean; best_score: number | null; pass_threshold: number; attempts_limit: number | null };
type Review = { attempt: { score: number; passed: boolean; attempt_no: number } | null; can_review: boolean; attempts_remaining: number | null; questions: { id: string; prompt: string; answer: string; is_correct?: boolean; correct_answer?: string; explanation?: string | null }[] };
type Result = { quiz_id: string; score: number; passed: boolean; correct: number; total: number; xp_awarded: number; replayed: boolean };
const btn = "gap-2 rounded-xl text-sm font-medium normal-case tracking-normal";

function parseQuestion(prompt: string) {
  const normalized = prompt.replace(/\r\n/g, "\n").replace(/\s+(?=[A-EАБВГД][).:]\s)/gu, "\n");
  const options: { label: string; text: string }[] = [], stem: string[] = [];
  const labels: Record<string, string> = { "А": "A", "Б": "B", "В": "C", "Г": "D", "Д": "E" };
  for (const line of normalized.split("\n")) {
    const match = /^\s*([A-EАБВГД])[).:]\s*(.+)$/u.exec(line);
    if (match) options.push({ label: labels[match[1]] || match[1], text: match[2].trim() });
    else if (options.length && line.trim()) options[options.length - 1].text += `\n${line.trim()}`;
    else stem.push(line);
  }
  return { stem: stem.join("\n").trim(), options };
}

export default function QuizPage() {
  const { quizId } = useParams<{ quizId: string }>();
  return <QuizWorkspace key={quizId} quizId={quizId} />;
}

function QuizWorkspace({ quizId }: { quizId: string }) {
  const { user } = useAuth();
  const [context, setContext] = useState<QuizContext | null>(null);
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<Result | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clock, setClock] = useState(Date.now());
  const [hasDraft, setHasDraft] = useState(false);
  const [sessionExpired, setSessionExpired] = useState(false);
  const inflight = useRef(false);
  const resultRef = useRef<HTMLDivElement>(null);
  const draftKey = user ? `corelms:quiz:${user.id}:${quizId}` : "";
  const answered = quiz?.questions.filter(q => answers[q.id]?.trim()).length || 0;
  const seconds = quiz?.time_limit ? Math.max(0, Math.ceil(quiz.started_at + quiz.time_limit - clock / 1000)) : null;
  const timedOut = seconds === 0;
  const theoryHref = context ? `/modules/${context.module_id}${context.submodule_id ? `?lesson=${context.submodule_id}` : ""}` : "/modules";
  const currentQuizHref = context ? `/quizzes/${context.current_quiz_id}` : "";

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const value = await apiFetch<QuizContext>(`/quizzes/${quizId}/context`, { signal });
      if (!signal?.aborted) setContext(value);
    } catch (e) { if (!signal?.aborted) setError(e instanceof Error ? e.message : "Не удалось загрузить тест"); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [quizId]);
  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);
  useEffect(() => {
    if (!draftKey) return;
    try { setHasDraft(!!sessionStorage.getItem(draftKey)); } catch { /* optional browser storage */ }
  }, [draftKey]);
  useEffect(() => {
    if (!quiz || result) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [quiz, result]);
  useEffect(() => {
    if (!draftKey || !quiz || result) return;
    try { sessionStorage.setItem(draftKey, JSON.stringify({ session_id: quiz.session_id, answers })); } catch { /* testing still works without local storage */ }
  }, [draftKey, quiz, answers, result]);
  useEffect(() => {
    if (!quiz || result || !Object.values(answers).some(Boolean)) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [quiz, result, answers]);

  async function start() {
    if (inflight.current) return;
    inflight.current = true; setBusy(true); setError(null);
    try {
      const next = await apiFetch<Quiz>(`/quizzes/${quizId}/start`, { method: "POST" });
      let restored: Record<string, string> = {};
      try {
        const draft = JSON.parse(draftKey && sessionStorage.getItem(draftKey) || "null");
        if (draft?.session_id === next.session_id) restored = Object.fromEntries(next.questions.filter(q => typeof draft.answers?.[q.id] === "string").map(q => [q.id, draft.answers[q.id]]));
      } catch { /* invalid/old drafts must not prevent a fresh attempt */ }
      setReview(null); setReviewError(null);
      setAnswers(restored); setQuiz(next); setResult(null); setSessionExpired(false); setClock(Date.now());
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось начать тест"); }
    finally { setBusy(false); inflight.current = false; }
  }

  async function submit() {
    if (!quiz || inflight.current || result) return;
    inflight.current = true; setBusy(true); setError(null);
    try {
      const next = await apiFetch<Result>(`/quizzes/${quizId}/submit`, {
        method: "POST", body: JSON.stringify({ session_id: quiz.session_id, answers: quiz.questions.map(q => ({ question_id: q.id, answer: answers[q.id] || "" })) }),
      });
      setResult(next); setHasDraft(false);
      try { if (draftKey) sessionStorage.removeItem(draftKey); localStorage.setItem("corelms:modules-updated", String(Date.now())); } catch { /* optional */ }
      void load();
      window.dispatchEvent(new Event("corelms:modules-updated"));
      window.dispatchEvent(new CustomEvent("corelms:refresh-me", { detail: { reason: "progress" } }));
      if (next.xp_awarded > 0 && !next.replayed) window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: `+${next.xp_awarded} XP`, description: next.passed ? "Тест пройден" : "Попытка сохранена" } }));
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 30);
    } catch (e) {
      const code = (e as { errorCode?: string }).errorCode;
      setSessionExpired(code === "session_expired" || code === "time_limit_exceeded");
      setError(e instanceof Error ? e.message : "Не удалось отправить ответы. Они сохранены — повторите отправку.");
    } finally { setBusy(false); inflight.current = false; }
  }

  async function showReview() {
    setReviewLoading(true); setReviewError(null);
    try { setReview(await apiFetch<Review>(`/quizzes/${quizId}/attempts/latest`)); }
    catch (e) { setReviewError(e instanceof Error ? e.message : "Не удалось загрузить разбор"); }
    finally { setReviewLoading(false); }
  }

  function updateAnswer(question: Question, value: string, multi: boolean) {
    setAnswers(previous => {
      if (!multi) return { ...previous, [question.id]: value };
      const selected = new Set((previous[question.id] || "").split(",").filter(Boolean));
      if (selected.has(value)) selected.delete(value); else selected.add(value);
      return { ...previous, [question.id]: [...selected].sort().join(",") };
    });
  }

  return <AppShell><div className="mx-auto max-w-6xl px-4 py-7 sm:px-6 lg:py-10">
    <Link href={theoryHref} className="mb-6 inline-flex items-center gap-2 text-sm text-zinc-500 hover:text-zinc-900"><ArrowLeft size={16} />{context?.submodule_id ? "К материалу урока" : "К модулю"}</Link>
    {loading ? <div role="status" className="flex min-h-80 items-center justify-center gap-3 text-zinc-500"><Loader2 className="animate-spin" />Загружаем тест…</div> : !context ? <div role="alert" className="rounded-2xl border border-zinc-200 bg-white p-8"><h1 className="text-xl font-semibold">Тест недоступен</h1><p className="my-4 text-sm text-zinc-500">{error}</p><Button className={btn} onClick={() => void load()}><RefreshCw size={16} />Повторить</Button></div> : <>
      <header className="mb-7"><p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-amber-700">{context.is_final ? "Итоговый тест" : "Проверка знаний"}</p><h1 className="text-2xl font-semibold tracking-tight text-zinc-950 sm:text-3xl">{context.title}</h1><p className="mt-2 text-sm text-zinc-500">{context.module_title}</p></header>
      {error && <div role="alert" className="mb-5 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm leading-relaxed text-rose-700">{error}{quiz && !sessionExpired && <p className="mt-1 font-medium">Ответы остаются на странице. Можно повторить отправку.</p>}</div>}
      <div className="grid items-start gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="space-y-4 lg:sticky lg:top-24">
          <section className="rounded-2xl border border-zinc-200 bg-white p-5"><div className="mb-4 flex items-center gap-2 text-sm font-semibold"><GraduationCap size={20} className="text-amber-600" />Ваш тест</div><dl className="space-y-3 text-sm"><div className="flex justify-between gap-3"><dt className="text-zinc-500">Проходной балл</dt><dd className="font-semibold tabular-nums">{quiz?.pass_threshold ?? context.pass_threshold}%</dd></div>{quiz && <div className="flex justify-between gap-3"><dt className="text-zinc-500">Попытка</dt><dd className="font-semibold tabular-nums">{quiz.attempt_no}{(quiz.attempts_limit ?? context.attempts_limit) ? ` из ${quiz.attempts_limit ?? context.attempts_limit}` : ""}</dd></div>}{context.best_score != null && <div className="flex justify-between gap-3"><dt className="text-zinc-500">Лучший результат</dt><dd className="font-semibold tabular-nums text-emerald-700">{context.best_score}%</dd></div>}</dl>
            {quiz && !result && <><div className="mb-2 mt-6 flex justify-between text-xs text-zinc-500"><span>Ответов заполнено</span><span className="tabular-nums">{answered} / {quiz.questions.length}</span></div><div className="h-1.5 rounded-full bg-zinc-100"><div className="h-full rounded-full bg-amber-500 transition-all" style={{ width: `${quiz.questions.length ? answered / quiz.questions.length * 100 : 0}%` }} /></div>{seconds !== null && <p className={cn("mt-4 flex items-center gap-2 text-sm tabular-nums", seconds < 60 ? "font-medium text-rose-700" : "text-zinc-600")}><Clock3 size={16} />{timedOut ? "Время истекло" : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`}</p>}</>}
            {!quiz ? <Button className={`mt-6 w-full ${btn}`} disabled={!context.can_start || busy} onClick={() => void start()}>{busy ? <Loader2 size={16} className="animate-spin" /> : <ArrowRight size={16} />}{busy ? "Загружаем…" : (hasDraft || context.can_resume) ? "Продолжить попытку" : context.passed ? "Пройти ещё раз" : "Начать тест"}</Button> : result ? <div className="mt-5 space-y-2"><Button asChild className={`w-full ${btn}`}><Link href={theoryHref}>Вернуться к обучению<ArrowRight size={16} /></Link></Button><Button variant="outline" className={`w-full ${btn}`} disabled={busy || !context.can_start} onClick={() => void start()}><RefreshCw size={15} />Новая попытка</Button></div> : timedOut || sessionExpired ? <Button onClick={() => void start()} disabled={busy} className={`mt-5 w-full ${btn}`}><RefreshCw size={16} />Начать заново</Button> : <Button className={`mt-6 w-full ${btn}`} onClick={() => void submit()} disabled={busy || answered !== quiz.questions.length}>{busy ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}{busy ? "Сохраняем результат…" : "Завершить тест"}</Button>}
            {!context.can_start && <p className="mt-3 text-xs leading-relaxed text-zinc-500">{context.start_blocked_reason || (context.is_final ? "Сначала завершите все уроки модуля." : "Откройте материал урока и подтвердите его изучение.")}</p>}
            {quiz && !result && <p className="mt-3 text-xs leading-relaxed text-zinc-400">Ответы сохраняются в этой вкладке. Повторное открытие не сбрасывает таймер и вопросы.</p>}
          </section>
          {context.passed && !result && <p className="flex gap-2 rounded-xl bg-emerald-50 p-4 text-xs leading-relaxed text-emerald-800"><ShieldCheck size={18} className="shrink-0" />Вы уже прошли этот урок или тест. Новая попытка не отменит лучший результат.</p>}
        </aside>
        <section className="min-w-0 space-y-5">
          {context.current_quiz_id !== quizId && <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-relaxed text-amber-900">Вопросы обновлены. Начатую попытку можно продолжить; для новой используйте <Link href={currentQuizHref} className="font-medium underline">актуальный тест</Link>.</div>}
          {result && <section ref={resultRef} role="status" className={cn("scroll-mt-24 rounded-2xl border p-6 sm:p-8", result.passed ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50")}><div className="flex items-center justify-between gap-4"><div><p className="mb-2 text-xs font-medium text-zinc-500">Результат сохранён</p><h2 className="text-xl font-semibold">{result.passed ? "Тест пройден!" : "Есть что повторить"}</h2></div><span className={cn("text-4xl font-semibold tabular-nums", result.passed ? "text-emerald-800" : "text-amber-800")}>{result.score}%</span></div><p className="mt-4 text-sm leading-relaxed text-zinc-600">Верных ответов: {result.correct} из {result.total}. {result.passed ? "Можете вернуться к материалам или продолжить обучение." : `Для зачёта нужно ${quiz?.pass_threshold ?? context.pass_threshold}%. Повторите материал и попробуйте ещё раз.`}</p></section>}
          {(!quiz || result) && (result || !!context.attempts_used) && <section className="space-y-4 rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-base font-semibold">Разбор последней попытки</h2><Button variant="outline" className={btn} disabled={reviewLoading} onClick={() => void showReview()}>{reviewLoading ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}{review ? "Обновить разбор" : "Посмотреть ответы"}</Button></div><p className="text-xs leading-6 text-zinc-500">Правильные ответы и объяснения открываются после успешного прохождения или исчерпания попыток.</p>{reviewError && <p role="alert" className="text-sm text-rose-700">{reviewError}</p>}{review && !review.attempt && <p className="text-sm text-zinc-500">В этой версии теста ещё нет завершённых попыток.</p>}{review?.attempt && <div className="space-y-3"><p className="text-sm text-zinc-600">Попытка {review.attempt.attempt_no} · {review.attempt.score}%{review.attempt.passed ? " · зачтена" : " · не зачтена"}</p>{!review.can_review && <p className="rounded-xl bg-amber-50 p-4 text-sm leading-6 text-amber-900">Повторите материал и попробуйте ещё раз.{review.attempts_remaining != null ? ` Осталось попыток: ${review.attempts_remaining}.` : ""}</p>}{review.can_review && review.questions.map((item, index) => <div key={item.id} className={cn("space-y-2 rounded-xl border p-4", item.is_correct ? "border-emerald-200 bg-emerald-50/50" : "border-amber-200 bg-amber-50/50")}><p className="text-xs font-semibold text-zinc-500">Вопрос {index + 1} · {item.is_correct ? "Верно" : "Нужно повторить"}</p><p className="whitespace-pre-wrap break-words text-sm leading-7 text-zinc-800">{item.prompt}</p><p className="text-xs leading-6 text-zinc-600">Ваш ответ: {item.answer || "Не указан"} · Правильный ответ: <strong>{item.correct_answer}</strong></p>{item.explanation && <p className="whitespace-pre-wrap break-words border-t border-zinc-200/60 pt-3 text-sm leading-7 text-zinc-700">{item.explanation}</p>}</div>)}</div>}</section>}
          {!quiz ? <section className="rounded-2xl border border-zinc-200 bg-white p-7 sm:p-10"><div className="mb-5 inline-flex rounded-2xl bg-amber-50 p-4 text-amber-700"><GraduationCap size={32} /></div><h2 className="text-2xl font-semibold tracking-tight">Проверьте, что вы запомнили</h2><p className="mt-4 max-w-xl text-sm leading-7 text-zinc-600">Внимательно прочитайте вопросы и выберите ответы. Для некоторых вопросов нужно отметить несколько вариантов. Результат появится сразу после отправки.</p><div className="mt-6 flex items-center gap-2 border-t border-zinc-100 pt-5 text-xs text-zinc-500"><CheckCircle2 size={16} className="text-emerald-700" />Обновления материалов не отменяют уже заработанные результаты.</div></section> : <>
            {quiz.questions.map((question, index) => {
              const parsed = parseQuestion(question.prompt);
              const multi = question.type === "multi";
              const chosen = new Set((answers[question.id] || "").split(",").filter(Boolean));
              return <fieldset key={question.id} disabled={!!result || busy || timedOut || sessionExpired} className="min-w-0 rounded-2xl border border-zinc-200 bg-white p-5 sm:p-7"><legend className="px-2 text-xs font-semibold text-zinc-500">Вопрос {index + 1} из {quiz.questions.length}</legend><p className="whitespace-pre-wrap break-words text-base font-medium leading-7 text-zinc-900">{parsed.stem || question.prompt}</p><p className="mb-4 mt-2 text-xs text-zinc-400">{question.type === "case" || !parsed.options.length ? "Напишите ответ своими словами" : multi ? "Выберите все подходящие варианты" : "Выберите один вариант"}</p>{parsed.options.length && question.type !== "case" ? <div className="space-y-2.5">{parsed.options.map(option => <label key={option.label} className={cn("flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 text-sm leading-relaxed transition-colors", chosen.has(option.label) ? "border-amber-400 bg-amber-50 text-zinc-900" : "border-zinc-200 text-zinc-600 hover:bg-zinc-50")}><input type={multi ? "checkbox" : "radio"} name={`question-${question.id}`} checked={chosen.has(option.label)} onChange={() => updateAnswer(question, option.label, multi)} className="mt-1 h-4 w-4 shrink-0 accent-amber-600" /><span className="shrink-0 font-semibold text-zinc-400">{option.label}.</span><span className="whitespace-pre-wrap break-words">{option.text}</span></label>)}</div> : <textarea aria-label={`Ответ на вопрос ${index + 1}`} rows={4} maxLength={20000} value={answers[question.id] || ""} onChange={event => updateAnswer(question, event.target.value, false)} placeholder="Ваш ответ…" className="w-full rounded-xl border border-zinc-200 px-4 py-3 text-sm leading-7 outline-none focus:border-amber-500 disabled:bg-zinc-50" />}</fieldset>;
            })}
            {!result && !timedOut && !sessionExpired && <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-zinc-200 bg-white p-5"><p className="text-xs text-zinc-500">{answered === quiz.questions.length ? "Все ответы заполнены. Можно отправлять." : `Осталось ответить: ${quiz.questions.length - answered}`}</p><Button className={btn} onClick={() => void submit()} disabled={busy || answered !== quiz.questions.length}>{busy ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}{busy ? "Сохраняем…" : "Завершить тест"}</Button></div>}
          </>}
        </section>
      </div>
    </>}
  </div></AppShell>;
}
