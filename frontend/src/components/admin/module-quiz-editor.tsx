"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Check, ChevronDown, GraduationCap, Loader2, Plus, RefreshCw, Save, ShieldCheck, Sparkles, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { EditorLesson, Workspace } from "./editor-types";

type Question = { id?: string | null; type: string; stem: string; options: string[]; correct: number[]; explanation: string; valid?: boolean };
type Quiz = { revision: number; quiz_id?: string; enabled: boolean; pass_threshold: number; time_limit: number | null; attempts_limit: number; questions: Question[]; source_lessons?: number };
type BatchItem = { lesson_id: string; title: string; status: string; questions: number; current_questions: number; required: boolean; error: string | null };
type Batch = { id: string | null; items: BatchItem[]; working: boolean; counts: Record<string, number>; remaining: number; message?: string };
type DraftJob = { id: string | null; status: string; error?: string; stale?: boolean; result?: { ok: boolean; revision: number; source_revision?: string; error?: string; questions?: Question[]; notice?: string | null; source_label?: string; source_chars?: number } };
const btn = "gap-2 rounded-xl text-sm font-medium normal-case tracking-normal";
const field = "w-full min-w-0 rounded-xl border border-zinc-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-100 disabled:bg-zinc-50";
const normalize = (quiz: Quiz): Quiz => ({ ...quiz, questions: quiz.questions || [] });
const running = (job: DraftJob | null) => !!job?.id && ["queued", "started", "scheduled", "deferred"].includes(job.status);

const stateLabel = (state: string) => state === "configured" ? "Уже есть тест" : state === "ready" ? "Черновик готов" : ["queued", "started", "scheduled", "deferred"].includes(state) ? "Готовится" : state === "needs_source" ? "Нужен текст" : state === "stale" ? "Материалы изменены" : state === "failed" ? "Ошибка" : "Не начато";
const batchLabel = (item: BatchItem) => item.status === "configured" ? `Готово: ${item.current_questions}` : item.status === "ready" ? `Черновик: ${item.questions}` : item.status === "queued" || item.status === "started" || item.status === "scheduled" || item.status === "deferred" ? "Готовится…" : item.status === "needs_source" ? "Нужен текст" : item.status === "stale" ? "Материалы изменены" : item.status === "failed" ? "Ошибка" : "Не начато";

export function ModuleQuizEditor({ moduleId, revision, lessons, initialLessonId, locked, aiConfigured, onWorkspace, onDirtyChange, onBusyChange }: {
  moduleId: string; revision: number; lessons: EditorLesson[]; initialLessonId: string | null; locked: boolean; aiConfigured: boolean;
  onWorkspace: (next: Workspace) => void; onDirtyChange: (dirty: boolean) => void; onBusyChange: (busy: boolean) => void;
}) {
  const available = lessons.filter(l => !l.is_folder && !l.is_archived);
  const [selected, setSelected] = useState(available.some(l => l.id === initialLessonId) ? initialLessonId! : available[0]?.id || "final");
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [saved, setSaved] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [job, setJob] = useState<DraftJob | null>(null);
  const [showAI, setShowAI] = useState(false);
  const [source, setSource] = useState("");
  const [count, setCount] = useState(5);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [batchLoading, setBatchLoading] = useState(true);
  const [batchTick, setBatchTick] = useState(0);
  const inFlight = useRef(false);
  const dirtyRef = useRef(false);
  const loadedPath = useRef("");
  const loadedRefresh = useRef(0);
  const isFinal = selected === "final";
  const base = `/admin/content/modules/${moduleId}`;
  const path = isFinal ? `${base}/final-quiz` : `${base}/lessons/${selected}/quiz`;
  const draftPath = `${base}/lessons/${selected}/quiz-draft`;
  const dirty = !!quiz && JSON.stringify(quiz) !== saved;
  const sourceDirty = showAI && !!source.trim();
  dirtyRef.current = dirty || sourceDirty;
  const currentLesson = available.find(l => l.id === selected);

  useEffect(() => { onDirtyChange(dirty || sourceDirty); }, [dirty, sourceDirty, onDirtyChange]);
  useEffect(() => { onBusyChange(busy); }, [busy, onBusyChange]);
  useEffect(() => () => { onDirtyChange(false); onBusyChange(false); }, [onDirtyChange, onBusyChange]);

  useEffect(() => {
    if (dirtyRef.current && loadedPath.current === path && loadedRefresh.current === refresh) {
      setError("Модуль изменён, но ваш несохранённый черновик не перезаписан. Обновите тест с сервера перед дальнейшим сохранением.");
      return;
    }
    loadedPath.current = path; loadedRefresh.current = refresh;
    const controller = new AbortController();
    setLoading(true); setError(null); setMessage(null); setJob(null); setShowAI(false); setSource("");
    void apiFetch<Quiz>(path, { signal: controller.signal }).then(value => {
      if (controller.signal.aborted) return;
      const next = normalize(value); setQuiz(next); setSaved(JSON.stringify(next));
    }).catch(e => { if (!controller.signal.aborted) { setQuiz(null); setError(e instanceof Error ? e.message : "Не удалось загрузить тест"); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    if (!isFinal) void apiFetch<DraftJob>(draftPath, { signal: controller.signal }).then(next => { if (!controller.signal.aborted) setJob(next); }).catch(() => {});
    return () => controller.abort();
  }, [path, draftPath, isFinal, refresh, revision]);

  useEffect(() => {
    if (!running(job)) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await apiFetch<DraftJob>(`${draftPath}?job_id=${encodeURIComponent(job!.id!)}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setJob(next);
        if (!running(next)) return;
      } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Статус AI временно недоступен"); }
      if (!controller.signal.aborted) timer = setTimeout(poll, document.hidden ? 15000 : 3500);
    };
    timer = setTimeout(poll, 1500);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [job?.id, job?.status, draftPath]);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    const poll = async () => {
      try {
        const next = await apiFetch<Batch>(`${base}/quiz-drafts`, { signal: controller.signal });
        if (stopped) return;
        setBatch(next); setBatchLoading(false);
        if (!next.working) return;
      } catch (e) {
        if (stopped) return;
        setBatchLoading(false);
        if (!controller.signal.aborted) setError(previous => previous || (e instanceof Error ? e.message : "Статус общей подготовки недоступен"));
      }
      if (!stopped) timer = setTimeout(poll, document.hidden ? 15000 : 4000);
    };
    void poll();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); };
  }, [base, revision, batchTick]);
  async function startBatch(onlyMissing = true) {
    if (inFlight.current || !available.length) return;
    inFlight.current = true; setBusy(true); setError(null); setMessage(null);
    try {
      const next = await apiFetch<Batch>(`${base}/quiz-drafts`, { method: "POST", body: JSON.stringify({ revision, count, only_missing: onlyMissing }) });
      setBatch(next); setBatchTick(n => n + 1);
      if (next.id) {
        setMessage("AI готовит тесты в фоне. Можно продолжать работу; результаты сохранятся на 7 дней и не изменят действующие тесты.");
        window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "Тесты готовятся", description: "Проверьте их перед включением" } }));
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось запустить подготовку тестов"); }
    finally { inFlight.current = false; setBusy(false); }
  }
  const edit = useCallback((update: Partial<Quiz>) => { setQuiz(old => old ? { ...old, ...update } : old); setMessage(null); }, []);
  function changeQuestion(index: number, update: Partial<Question>) {
    if (!quiz) return;
    edit({ questions: quiz.questions.map((q, i) => i === index ? { ...q, ...update, valid: undefined } : q) });
  }
  function validation(): string | null {
    if (!quiz) return "Тест не загружен";
    if (quiz.pass_threshold < 1 || quiz.pass_threshold > 100) return "Проходной балл: от 1 до 100%.";
    if (quiz.attempts_limit < 0 || quiz.attempts_limit > 100) return "Число попыток: от 0 до 100 (0 — без лимита).";
    if (quiz.time_limit !== null && (quiz.time_limit < 60 || quiz.time_limit > 14400)) return "Время: от 1 до 240 минут или пустое поле для теста без таймера.";
    if (isFinal) return quiz.enabled && !quiz.source_lessons ? "Сначала включите тест хотя бы в одном уроке." : null;
    if (quiz.enabled && !quiz.questions.length) return "Добавьте хотя бы один вопрос или выключите обязательный тест.";
    for (const [index, question] of quiz.questions.entries()) {
      const prefix = `Вопрос ${index + 1}: `;
      if (!["single", "multi"].includes(question.type)) return prefix + "выберите проверку по вариантам ответа.";
      if (!question.stem.trim() || question.options.length < 2 || question.options.length > 5 || question.options.some(o => !o.trim())) return prefix + "заполните формулировку и от 2 до 5 вариантов.";
      if (new Set(question.options.map(o => o.trim().toLocaleLowerCase("ru"))).size !== question.options.length) return prefix + "варианты не должны совпадать.";
      const hasOptionLabel = (line: string) => /^[A-EАБВГД][).:]/i.test(line.trim());
      if (question.stem.split(/\r?\n/).some(hasOptionLabel) || question.options.some(option => option.split(/\r?\n/).slice(1).some(hasOptionLabel))) {
        return prefix + "не вставляйте списки A), B) в формулировку или внутрь варианта — используйте отдельные поля ответов.";
      }
      if (!question.correct.length || question.correct.some(i => i < 0 || i >= question.options.length) || (question.type === "single" && question.correct.length !== 1)) return prefix + "отметьте правильный ответ.";
    }
    return null;
  }
  const invalid = validation();

  async function save() {
    if (!quiz || inFlight.current || invalid) return;
    inFlight.current = true; setBusy(true); setError(null);
    try {
      if (isFinal) {
        const workspace = await apiFetch<Workspace>(path, { method: "PUT", body: JSON.stringify(quiz) });
        const next = { ...quiz, revision: workspace.module.content_revision }; setQuiz(next); setSaved(JSON.stringify(next)); onWorkspace(workspace);
      } else {
        const next = await apiFetch<{ workspace: Workspace; quiz: Quiz }>(path, { method: "PUT", body: JSON.stringify(quiz) });
        const normalized = normalize(next.quiz); setQuiz(normalized); setSaved(JSON.stringify(normalized)); onWorkspace(next.workspace);
      }
      setMessage("Сохранено. Старые попытки, ответы и заработанный прогресс сохранены.");
      window.dispatchEvent(new CustomEvent("corelms:toast", { detail: { title: "Тест сохранён", description: "История попыток и прогресс сохранены" } }));
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось сохранить тест"); }
    finally { inFlight.current = false; setBusy(false); }
  }
  async function generate() {
    if (!quiz || inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(null); setMessage(null);
    try {
      const next = await apiFetch<DraftJob>(draftPath, { method: "POST", body: JSON.stringify({ revision: quiz.revision, count, source_text: source.trim() || null }) });
      setJob(next); setShowAI(false);
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось запустить AI"); }
    finally { inFlight.current = false; setBusy(false); }
  }
  // The server fingerprints only this lesson's materials, so editing another
  // lesson or publishing the module cannot invalidate a reviewed draft.
  const staleDraft = !!job?.stale;

  return <div className="mt-6 space-y-5">
    <section className="rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6">
      <div className="mb-5 flex items-start gap-3"><GraduationCap size={23} className="mt-1 shrink-0 text-amber-700" /><div><h2 className="text-lg font-semibold">Проверка знаний</h2><p className="mt-1 text-sm leading-7 text-zinc-500">Вопросы, правильные ответы и правила прохождения — здесь. AI создаёт только черновик, который вы проверяете перед сохранением.</p></div></div>
      {!!available.length && <div className="mt-4 rounded-xl border border-zinc-200 bg-zinc-50/60 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><div className="min-w-0"><p className="text-sm font-medium">Подготовить тесты для всех уроков</p><p className="mt-1 text-xs leading-6 text-zinc-500">{batch?.items.length ? `В подготовке ${batch.items.length}` : `${available.filter(lesson => !lesson.question_count).length} без вопросов`} из {available.length} уроков. Один запуск создаёт черновики; действующие тесты не меняются.</p></div>
          <div className="flex flex-wrap gap-2"><label className="flex items-center gap-2 text-xs text-zinc-500">Вопросов на урок<input type="number" min={1} max={10} aria-label="Вопросов на урок" className={`${field} !w-20`} value={count} onChange={e => setCount(Number(e.target.value))} /></label>
            <Button className={btn} disabled={locked || busy || !aiConfigured} onClick={() => void startBatch(true)}><Sparkles size={16} />Только без тестов</Button>
            <Button variant="outline" className={btn} disabled={locked || busy || !aiConfigured} onClick={() => void startBatch(false)}>Все уроки</Button></div></div>
        {!aiConfigured && <p className="mt-3 rounded-lg bg-amber-50 p-3 text-xs leading-6 text-amber-900">AI пока не настроен. Создайте вопросы вручную или <Link href="/admin/settings" className="font-semibold underline">укажите токен в настройках</Link> — всё остальное работает без AI.</p>}
        {batchLoading ? <p role="status" className="mt-3 text-xs text-zinc-500">Проверяем общую подготовку…</p> : batch && (batch.items.length > 0 || batch.message) && <div className="mt-3 space-y-2">
          {!!batch.items.length && <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500"><span>{batch.working ? "Идёт подготовка." : "Подготовка завершена."}</span>{Object.entries(batch.counts || {}).filter(([, n]) => n > 0).map(([state, n]) => <span key={state} className={cn("rounded-full px-2 py-0.5", state === "failed" || state === "needs_source" || state === "stale" ? "bg-amber-100 text-amber-900" : "bg-white text-zinc-600")}>{stateLabel(state)} · {n}</span>)}</div>}
          {!!batch.remaining && <p className="text-xs leading-6 text-zinc-500">Ещё {batch.remaining} уроков не вошли в один запуск (до 50 за раз). Запустите подготовку повторно после проверки.</p>}
          {batch.message && <p className="text-xs leading-6 text-zinc-500">{batch.message}</p>}
          {batch.items.length > 0 && <ul className="grid gap-1.5 sm:grid-cols-2">{batch.items.map(item => <li key={item.lesson_id} className="flex flex-wrap items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs"><span className="min-w-0 flex-1 break-words">{item.title}</span><span className={cn("shrink-0 rounded-full px-2 py-0.5", item.status === "configured" ? "bg-emerald-50 text-emerald-800" : ["queued", "started", "scheduled", "deferred"].includes(item.status) ? "bg-zinc-100 text-zinc-600" : "bg-amber-50 text-amber-900")}>{batchLabel(item)}</span><button type="button" className="shrink-0 font-medium text-amber-800 underline" onClick={() => { if ((!dirty && !sourceDirty) || window.confirm("Переключить тест без сохранения изменений?")) { setSelected(item.lesson_id); setShowAI(false); } }}>Открыть</button></li>)}</ul>}
        </div>}
      </div>}
      <label className="mt-5 block space-y-2 text-sm font-medium">Какой тест редактируем<select aria-label="Тест для редактирования" className={field} value={selected} disabled={busy} onChange={e => { if ((!dirty && !sourceDirty) || window.confirm("Переключить тест без сохранения изменений?")) setSelected(e.target.value); }}>{available.map(l => <option key={l.id} value={l.id}>{l.question_count ? `${l.title} · ${l.question_count} вопр.` : `${l.title} · без вопросов`}{l.requires_quiz ? " · обязателен" : ""}</option>)}<option value="final">Итоговый тест модуля</option></select></label>
    </section>
    {error && <div role="alert" className="space-y-2 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"><p>{error}</p><button type="button" className="font-medium underline" onClick={() => { if ((!dirty && !sourceDirty) || window.confirm("Загрузить текущую версию с сервера без сохранения черновика?")) setRefresh(n => n + 1); }}>Обновить тест с сервера</button></div>}
    {loading ? <p role="status" className="flex items-center justify-center gap-2 py-12 text-sm text-zinc-500"><Loader2 className="animate-spin" size={20} />Загружаем вопросы…</p> : quiz && <>
      <section className="rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6">
        <label className="flex cursor-pointer items-start gap-3 text-sm font-medium"><input type="checkbox" checked={quiz.enabled} disabled={locked} onChange={e => edit({ enabled: e.target.checked })} className="mt-0.5 h-4 w-4 shrink-0 accent-amber-600" /><span>{isFinal ? "Включить итоговый тест модуля" : "Требовать прохождение теста этого урока"}<span className="mt-1 block text-xs font-normal leading-6 text-zinc-500">{isFinal ? "До 3 вопросов из каждого обязательного теста урока. Если уроков больше 10, выбирается до 10 уроков — максимум 30 вопросов." : "Без обязательного теста урок завершается после подтверждения изучения. Подготовленный банк вопросов можно сохранить и включить позже."}</span></span></label>
        <div className="mt-5 grid gap-4 sm:grid-cols-3">
          <label className="space-y-2 text-xs font-medium text-zinc-600">Проходной балл, %<input type="number" min={1} max={100} className={field} value={quiz.pass_threshold} disabled={locked} onChange={e => edit({ pass_threshold: Number(e.target.value) })} /></label>
          <label className="space-y-2 text-xs font-medium text-zinc-600">Время, минут<input type="number" min={1} max={240} step={0.5} placeholder="Без таймера" className={field} value={quiz.time_limit == null ? "" : quiz.time_limit / 60} disabled={locked} onChange={e => edit({ time_limit: e.target.value ? Math.round(Number(e.target.value) * 60) : null })} /></label>
          <label className="space-y-2 text-xs font-medium text-zinc-600">Попытки · 0 — без лимита<input type="number" min={0} max={100} className={field} value={quiz.attempts_limit} disabled={locked} onChange={e => edit({ attempts_limit: Number(e.target.value) })} /></label>
        </div>
        {isFinal && <p className="mt-4 rounded-xl bg-zinc-50 p-4 text-sm leading-7 text-zinc-600">Источник — обязательные тесты {quiz.source_lessons || 0} уроков. Отдельного дублирующего банка у итогового теста нет. Изменения правил не меняют условия уже начатой попытки.</p>}
      </section>
      {!isFinal && <>
        <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-base font-semibold">Вопросы · {quiz.questions.length}</h3><div className="flex flex-wrap gap-2"><Button variant="outline" className={btn} disabled={locked || !aiConfigured || running(job)} onClick={() => setShowAI(v => !v)}><Sparkles size={16} />AI-черновик<ChevronDown size={14} /></Button><Button variant="outline" className={btn} disabled={locked || quiz.questions.length >= 100} onClick={() => edit({ questions: [...quiz.questions, { type: "single", stem: "", options: ["", ""], correct: [], explanation: "" }] })}><Plus size={16} />Добавить вопрос</Button></div></div>
        {showAI && <section className="space-y-4 rounded-2xl border border-amber-200 bg-amber-50/50 p-5 sm:p-6"><h3 className="flex items-center gap-2 font-medium"><Sparkles size={18} />Черновик по материалам урока</h3><p className="text-xs leading-6 text-zinc-600">Текст отправится настроенному AI-провайдеру. Пустое поле — использовать основной документ, а если извлечь текст нельзя — конспект урока. При показе текста первым источником будет текст урока. Для видео нужен конспект: автоматической расшифровки речи нет. За один черновик используется до 12 000 символов. Для длинного урока выбирайте нужный раздел. Существующие вопросы не изменятся.</p><label className="block space-y-2 text-sm font-medium">Текст для генерации <span className="font-normal text-zinc-400">(необязательно)</span><textarea rows={6} maxLength={60000} className={field} value={source} onChange={e => setSource(e.target.value)} placeholder={`Содержательные материалы урока «${currentLesson?.title || ""}»…`} /></label><div className="flex flex-wrap items-center gap-3"><label className="flex items-center gap-2 text-sm">Вопросов<input type="number" min={1} max={10} className={`${field} !w-20`} value={count} onChange={e => setCount(Number(e.target.value))} /></label><Button className={btn} disabled={locked || count < 1 || count > 10} onClick={() => void generate()}><Sparkles size={16} />Создать черновик</Button></div></section>}
        {running(job) && <p role="status" className="flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><Loader2 className="shrink-0 animate-spin" size={18} />AI готовит черновик. Можно продолжать работу или закрыть страницу — результат хранится 7 дней.</p>}
        {job?.result?.ok && <div className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><p><strong>Черновик готов: {job.result.questions?.length || 0} вопросов.</strong> Проверьте факты, однозначность вариантов и отмеченные правильные ответы.</p>{job.result.source_label && <p className="text-xs leading-6">Источник: {job.result.source_label} · {job.result.source_chars?.toLocaleString("ru-RU")} символов. Проверьте, что это нужный материал.</p>}{job.result.notice && <p className="text-xs leading-6">{job.result.notice}</p>}{staleDraft ? <p>Материалы этого урока изменены. Создайте новый черновик — остальные уроки и действующие тесты не затронуты.</p> : <div className="flex flex-wrap gap-2">{quiz.questions.length > 0 && <Button variant="outline" className={btn} disabled={locked || quiz.questions.length + (job.result.questions?.length || 0) > 100} onClick={() => { edit({ questions: [...quiz.questions, ...(job.result!.questions || [])] }); setMessage("Новые вопросы добавлены к черновику. Проверьте их перед сохранением."); }}><Plus size={16} />Добавить к вопросам</Button>}<Button variant="outline" className={btn} disabled={locked} onClick={() => { if ((!quiz.questions.length && !dirty) || window.confirm("Заменить вопросы в редакторе AI-черновиком? Действующий тест изменится только после вашего сохранения.")) { edit({ questions: job.result!.questions || [] }); setMessage("Черновик перенесён в редактор, но ещё не сохранён. Проверьте каждый вопрос."); } }}><Check size={16} />Подставить в редактор для проверки</Button></div>}</div>}
        {(job?.error || job?.result?.error) && <p role="alert" className="rounded-xl bg-amber-50 p-4 text-sm leading-7 text-amber-900">{job.error || job.result?.error}</p>}
        {!quiz.questions.length && <div className="rounded-2xl border border-dashed border-zinc-300 p-8 text-center text-sm leading-7 text-zinc-500">Пока нет вопросов. Добавьте первый вручную или создайте AI-черновик.<br />Пустые и непроверенные вопросы не публикуются автоматически.</div>}
        {quiz.questions.map((question, index) => <section key={question.id || `draft-${index}`} className="min-w-0 space-y-4 rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6">
          <div className="flex items-center justify-between gap-3"><h4 className="text-sm font-semibold">Вопрос {index + 1}</h4><button type="button" title="Удалить вопрос из редактора" aria-label={`Удалить вопрос ${index + 1}`} disabled={locked} onClick={() => { if (!question.stem || window.confirm("Убрать этот вопрос? Изменение вступит в силу после сохранения теста.")) edit({ questions: quiz.questions.filter((_, i) => i !== index) }); }} className="rounded-lg p-2 text-zinc-400 hover:bg-rose-50 hover:text-rose-600 disabled:opacity-40"><Trash2 size={16} /></button></div>
          {question.valid === false && <p className="rounded-lg bg-amber-50 p-3 text-xs leading-6 text-amber-900">Старый формат вопроса требует проверки. Заполните формулировку, варианты и правильные ответы.</p>}
          <label className="block space-y-2 text-sm font-medium">Формулировка<textarea aria-label={`Формулировка вопроса ${index + 1}`} rows={3} maxLength={12000} disabled={locked} className={field} value={question.stem} onChange={e => changeQuestion(index, { stem: e.target.value })} /></label>
          <label className="block space-y-2 text-sm font-medium">Тип ответа<select className={field} value={question.type} disabled={locked} onChange={e => changeQuestion(index, { type: e.target.value, options: question.options.length ? question.options : ["", ""], correct: e.target.value === "single" ? question.correct.slice(0, 1) : question.correct })}>{!["single", "multi"].includes(question.type) && <option value={question.type}>Неподдерживаемый старый формат</option>}<option value="single">Один правильный ответ</option><option value="multi">Несколько правильных ответов</option></select></label>
          <fieldset disabled={locked} className="space-y-2"><legend className="mb-3 text-xs font-medium text-zinc-500">Варианты · отметьте правильные ответы</legend>{question.options.map((option, optionIndex) => <div key={optionIndex} className={cn("flex items-start gap-2 rounded-xl border p-2 sm:gap-3 sm:p-3", question.correct.includes(optionIndex) ? "border-emerald-200 bg-emerald-50/40" : "border-zinc-100")}>
            <input type={question.type === "single" ? "radio" : "checkbox"} name={`correct-${index}`} aria-label={`Вопрос ${index + 1}: правильный вариант ${"ABCDE"[optionIndex]}`} checked={question.correct.includes(optionIndex)} onChange={e => changeQuestion(index, { correct: question.type === "single" ? [optionIndex] : e.target.checked ? [...question.correct, optionIndex].sort() : question.correct.filter(n => n !== optionIndex) })} className="mt-3 h-4 w-4 shrink-0 accent-emerald-700" />
            <span className="mt-3 text-xs font-medium text-zinc-400">{"ABCDE"[optionIndex]}</span><textarea rows={2} maxLength={3000} aria-label={`Вопрос ${index + 1}: вариант ${"ABCDE"[optionIndex]}`} className={`${field} flex-1`} value={option} onChange={e => changeQuestion(index, { options: question.options.map((text, i) => i === optionIndex ? e.target.value : text) })} />
            <button type="button" aria-label={`Удалить вариант ${"ABCDE"[optionIndex]} вопроса ${index + 1}`} disabled={question.options.length <= 2} onClick={() => changeQuestion(index, { options: question.options.filter((_, i) => i !== optionIndex), correct: question.correct.filter(n => n !== optionIndex).map(n => n > optionIndex ? n - 1 : n) })} className="mt-1 rounded-lg p-2 text-zinc-400 hover:text-rose-600 disabled:opacity-20"><X size={14} /></button>
          </div>)}<Button type="button" variant="ghost" size="sm" className={btn} disabled={locked || question.options.length >= 5} onClick={() => changeQuestion(index, { options: [...question.options, ""] })}><Plus size={14} />Ещё вариант</Button></fieldset>
          <label className="block space-y-2 text-sm font-medium">Объяснение <span className="font-normal text-zinc-400">(для разбора после теста)</span><textarea rows={2} maxLength={5000} className={field} disabled={locked} value={question.explanation} onChange={e => changeQuestion(index, { explanation: e.target.value })} /></label>
        </section>)}
      </>}
      <div className="sticky bottom-3 z-10 space-y-3 rounded-2xl border border-zinc-200 bg-white/95 p-4 shadow-lg backdrop-blur-sm">
        {message && <p role="status" className="text-sm leading-6 text-emerald-800">{message}</p>}
        {dirty && invalid && <p role="alert" className="text-sm leading-6 text-amber-800">{invalid}</p>}
        <div className="flex flex-wrap items-center justify-between gap-3"><p className="flex items-center gap-2 text-xs leading-6 text-zinc-500"><ShieldCheck size={16} className="shrink-0 text-emerald-700" />{dirty ? "Есть несохранённые изменения" : "Действующая версия загружена"}</p><div className="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto"><Button variant="ghost" className={`${btn} !px-3`} disabled={locked || !dirty} onClick={() => { if (window.confirm("Отменить несохранённые изменения этого теста?")) setRefresh(n => n + 1); }}><RefreshCw size={15} />Отменить</Button><Button aria-label="Сохранить тест" className={`${btn} !px-3`} disabled={locked || !dirty || !!invalid} onClick={() => void save()}>{busy ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}<span className="sm:hidden">Сохранить</span><span className="hidden sm:inline">Сохранить тест</span></Button></div></div>
      </div>
    </>}
  </div>;
}
