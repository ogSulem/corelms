"use client";

import { Button } from "@/components/ui/button";
import { AdminModuleItem, AdminSubmoduleItem, AdminSubmoduleQualityItem } from "../adminpanel-client";

interface ModulesTabProps {
  adminModules: AdminModuleItem[];
  adminModulesLoading: boolean;
  loadAdminModules: () => Promise<void>;
  selectedAdminModuleId: string;
  setSelectedAdminModuleId: (id: string) => void;
  selectedAdminModule: AdminModuleItem | null;
  setSelectedModuleVisibility: (active: boolean) => Promise<void>;
  activeModuleRegenByModuleId: Record<string, { job_id: string; status: string; stage: string }>;
  activeSubmoduleRegenBySubmoduleId: Record<string, { job_id: string; status: string; stage: string; module_id: string }>;
  regenerateSelectedModuleQuizzes: () => Promise<void>;
  deleteSelectedModule: () => Promise<void>;
  selectedAdminModuleSubsLoading: boolean;
  selectedAdminModuleSubs: AdminSubmoduleItem[];
  selectedAdminModuleSubsQuality: AdminSubmoduleQualityItem[];
  selectedAdminModuleSubsQualityLoading: boolean;
  regenerateSubmoduleQuiz: (submoduleId: string) => Promise<void>;
  selectedSubmoduleId: string;
  setSelectedSubmoduleId: (id: string) => void;
  setSelectedQuizId: (id: string) => void;
  selectedQuizId: string;
  newQuestionBusy: boolean;
  createQuestionAdmin: (quizId: string) => Promise<void>;
  questionsLoadingQuizId: string;
  loadQuestionsForQuiz: (quizId: string) => Promise<void>;
  selectedQuizQuestions: any[];
  isQuestionDirty: (q: any) => boolean;
  questionSavingId: string;
  saveQuestionDraft: (id: string) => Promise<void>;
  copy: (text: string) => void;
  deleteQuestionAdmin: (id: string) => Promise<void>;
  getDraftValue: (q: any, key: string) => any;
  setQuestionDraftsById: React.Dispatch<React.SetStateAction<Record<string, any>>>;
}

export function ModulesTab(props: ModulesTabProps) {
  const {
    adminModules,
    adminModulesLoading,
    loadAdminModules,
    selectedAdminModuleId,
    setSelectedAdminModuleId,
    selectedAdminModule,
    setSelectedModuleVisibility,
    activeModuleRegenByModuleId,
    activeSubmoduleRegenBySubmoduleId,
    regenerateSelectedModuleQuizzes,
    deleteSelectedModule,
    selectedAdminModuleSubsLoading,
    selectedAdminModuleSubs,
    selectedAdminModuleSubsQuality,
    selectedAdminModuleSubsQualityLoading,
    regenerateSubmoduleQuiz,
    selectedSubmoduleId,
    setSelectedSubmoduleId,
    setSelectedQuizId,
    selectedQuizId,
    newQuestionBusy,
    createQuestionAdmin,
    questionsLoadingQuizId,
    loadQuestionsForQuiz,
    selectedQuizQuestions,
    isQuestionDirty,
    questionSavingId,
    saveQuestionDraft,
    copy,
    deleteQuestionAdmin,
    getDraftValue,
    setQuestionDraftsById,
  } = props;

  const qualityBySubId = (() => {
    const out: Record<string, AdminSubmoduleQualityItem> = {};
    for (const it of selectedAdminModuleSubsQuality || []) {
      const sid = String((it as any)?.submodule_id || "").trim();
      if (!sid) continue;
      out[sid] = it;
    }
    return out;
  })();

  return (
    <div className="mt-8 space-y-6">
      <div className="grid gap-6 lg:grid-cols-12 items-start min-w-0">
        <div className="lg:col-span-4 relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-6 shadow-2xl shadow-zinc-950/10 min-w-0">
          <div className="flex items-end justify-between gap-6">
            <div>
              <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">МОДУЛИ</div>
              <div className="mt-2 text-xl font-black tracking-tighter text-zinc-950 uppercase">СПИСОК</div>
            </div>
            <Button
              variant="ghost"
              className="h-12 rounded-2xl font-black uppercase tracking-widest text-[9px]"
              disabled={adminModulesLoading}
              onClick={() => void loadAdminModules()}
            >
              {adminModulesLoading ? "..." : "ОБНОВИТЬ"}
            </Button>
          </div>

          <div className="mt-5 grid gap-1.5 max-h-[520px] overflow-y-auto overflow-x-hidden pr-1 min-w-0">
            {(adminModules || []).map((m: AdminModuleItem) => {
              const active = String(m.id) === String(selectedAdminModuleId);
              const q = m.question_quality;
              const needs = Number(q?.needs_regen_current || 0) > 0;
              const heur = Number(q?.heur_current || 0) > 0;
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => setSelectedAdminModuleId(String(m.id))}
                  className={
                    "w-full text-left rounded-2xl border px-3 py-2 transition " +
                    (active ? "border-[#fe9900]/25 bg-[#fe9900]/10" : "border-zinc-200 bg-white hover:bg-zinc-50")
                  }
                >
                  <div className="flex items-start justify-between gap-3 min-w-0">
                    <div className="min-w-0">
                      <div className="truncate text-[10px] font-black uppercase tracking-[0.22em] text-zinc-950">
                        {m.title}
                      </div>
                      <div className="mt-1 truncate text-[9px] font-black uppercase tracking-[0.22em] text-zinc-600">
                        {m.is_active ? "АКТИВЕН" : needs ? "НЕОБХОДИМ РЕГЕН (СКРЫТ ДО ГОТОВНОСТИ)" : heur ? "ЭВРИСТИКА (МОЖНО ПОКАЗАТЬ)" : "СКРЫТ"}
                      </div>
                    </div>
                    <div
                      className={
                        "shrink-0 rounded-full px-2.5 py-1 text-[9px] font-black uppercase tracking-[0.22em] border " +
                        (m.is_active
                          ? "border-[#284e13]/20 bg-[#284e13]/10 text-[#284e13]"
                          : needs
                            ? "border-[#fe9900]/25 bg-[#fe9900]/10 text-[#fe9900]"
                            : heur
                              ? "border-zinc-200 bg-zinc-50 text-zinc-700"
                              : "border-zinc-200 bg-zinc-50 text-zinc-700")
                      }
                    >
                      {m.is_active ? "АКТИВЕН" : needs ? "REGEN" : heur ? "HEUR" : "СКРЫТ"}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="lg:col-span-8 relative overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-10 shadow-2xl shadow-zinc-950/10">
          <div className="flex flex-wrap items-start justify-between gap-6">
            <div>
              <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900] mb-2">КАРТОЧКА</div>
              <div className="text-2xl font-black tracking-tighter text-zinc-950 uppercase leading-none">
                {selectedAdminModule ? selectedAdminModule.title : selectedAdminModuleId ? "ЗАГРУЗКА..." : "ВЫБЕРИТЕ МОДУЛЬ"}
              </div>
              {selectedAdminModule ? (
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <div className="text-sm text-zinc-500 font-bold uppercase tracking-widest">
                    {selectedAdminModule.is_active ? "ВИДИМ СОТРУДНИКАМ" : "СКРЫТ"}
                  </div>
                  <Button
                    variant={selectedAdminModule.is_active ? "outline" : "primary"}
                    className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                    onClick={() => void setSelectedModuleVisibility(!selectedAdminModule.is_active)}
                  >
                    {selectedAdminModule.is_active ? "СКРЫТЬ" : "ПОКАЗАТЬ"}
                  </Button>
                </div>
              ) : null}
            </div>

            <div className="shrink-0 flex flex-col gap-2">
              {selectedAdminModuleId && activeModuleRegenByModuleId[String(selectedAdminModuleId || "")] ? (
                <div className="h-11 rounded-xl border border-[#fe9900]/25 bg-[#fe9900]/10 px-4 flex items-center justify-center text-[10px] font-black uppercase tracking-widest text-[#fe9900]">
                  РЕГЕН ЗАПУЩЕН
                </div>
              ) : (
                <Button
                  variant="primary"
                  className="h-11 rounded-xl shadow-xl shadow-[#fe9900]/20"
                  disabled={!selectedAdminModuleId}
                  onClick={() => void regenerateSelectedModuleQuizzes()}
                >
                  РЕГЕН ТЕСТОВ
                </Button>
              )}
              <Button
                variant="destructive"
                className="h-11 rounded-xl font-black uppercase tracking-widest text-[9px]"
                disabled={!selectedAdminModuleId}
                onClick={() => void deleteSelectedModule()}
              >
                УДАЛИТЬ
              </Button>
            </div>
          </div>

          <div className="mt-10 space-y-10">
            <div>
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Уроки</div>
                  <div className="mt-2 text-lg font-black text-zinc-950 uppercase">Подмодули</div>
                </div>
                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-600">
                  {selectedAdminModuleSubs.length}
                </div>
              </div>

              <div className="mt-5">
                {selectedAdminModuleId && activeModuleRegenByModuleId[String(selectedAdminModuleId || "")] ? (
                  <div className="mb-3 rounded-2xl border border-[#fe9900]/25 bg-[#fe9900]/10 p-4">
                    <div className="text-[9px] font-black uppercase tracking-widest text-[#fe9900]">РЕГЕН МОДУЛЯ В ПРОЦЕССЕ</div>
                    <div className="mt-1 text-[11px] font-bold text-zinc-800">Все кнопки регена временно заблокированы</div>
                  </div>
                ) : null}

                {selectedAdminModuleSubsLoading ? (
                  <div className="py-10 text-center text-[10px] font-black uppercase tracking-widest text-zinc-600">
                    Загрузка...
                  </div>
                ) : selectedAdminModuleSubs.length === 0 ? (
                  <div className="py-10 text-center text-[10px] font-black uppercase tracking-widest text-zinc-600">
                    {selectedAdminModuleId ? "Нет уроков" : "Выберите модуль"}
                  </div>
                ) : (
                  <div className="grid gap-2 lg:grid-cols-2">
                    {selectedAdminModuleSubs.map((s: AdminSubmoduleItem) => {
                      const active = String(s.id) === String(selectedSubmoduleId);
                      const q = qualityBySubId[String(s.id)] as any;
                      const ok = q ? !!q.ok : false;
                      const needs = q ? Number(q.needs_regen || 0) : 0;
                      const total = q ? Number(q.total || 0) : 0;
                      const moduleRegenRunning = !!activeModuleRegenByModuleId[String(selectedAdminModuleId || "")];
                      const subRegenRunning = !!activeSubmoduleRegenBySubmoduleId[String(s.id)];
                      const subJob = activeSubmoduleRegenBySubmoduleId[String(s.id)];
                      return (
                        <div
                          key={s.id}
                          className={
                            "w-full rounded-xl border px-4 py-3 transition " +
                            (active ? "border-[#fe9900]/25 bg-[#fe9900]/10" : "border-zinc-200 bg-white hover:bg-zinc-50")
                          }
                        >
                          <div className="flex items-start justify-between gap-3">
                            <button
                              type="button"
                              onClick={() => {
                                setSelectedSubmoduleId(s.id);
                                setSelectedQuizId(String(s.quiz_id || ""));
                              }}
                              className="min-w-0 flex-1 text-left"
                            >
                              <div className="flex items-center gap-3">
                                <div className="h-6 w-6 rounded-lg bg-zinc-100 flex items-center justify-center text-[10px] font-black text-zinc-500">
                                  {s.order}
                                </div>
                                <div className="truncate text-[11px] font-black uppercase tracking-widest text-zinc-950">
                                  {s.title}
                                </div>
                              </div>
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                <div
                                  className={
                                    "inline-flex items-center rounded-full border px-3 py-1 text-[9px] font-black uppercase tracking-widest " +
                                    (ok
                                      ? "border-[#284e13]/20 bg-[#284e13]/10 text-[#284e13]"
                                      : "border-[#fe9900]/25 bg-[#fe9900]/10 text-[#fe9900]")
                                  }
                                >
                                  {q ? (ok ? "OK" : "NEEDS") : selectedAdminModuleSubsQualityLoading ? "..." : "—"}
                                </div>
                                {q ? (
                                  <>
                                    <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                      {total}/5
                                    </div>
                                    <div className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-zinc-700">
                                      needs {needs}
                                    </div>
                                  </>
                                ) : null}
                              </div>
                            </button>

                            {moduleRegenRunning || subRegenRunning ? (
                              <div className="h-9 rounded-xl border border-[#fe9900]/25 bg-[#fe9900]/10 px-3 flex items-center justify-center text-[9px] font-black uppercase tracking-widest text-[#fe9900]">
                                {moduleRegenRunning ? "РЕГЕН МОДУЛЯ" : "РЕГЕН УРОКА"}
                                {subJob?.job_id ? ` · ${String(subJob.job_id).slice(0, 6)}` : ""}
                              </div>
                            ) : (
                              <Button
                                variant="outline"
                                className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                                disabled={!s.id}
                                onClick={() => void regenerateSubmoduleQuiz(String(s.id))}
                              >
                                REGEN УРОКА
                              </Button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Опросы</div>
                  <div className="mt-2 text-lg font-black text-zinc-950 uppercase">Вопросы теста</div>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                    disabled={!selectedQuizId || newQuestionBusy}
                    onClick={() => void createQuestionAdmin(selectedQuizId)}
                  >
                    + ДОБАВИТЬ
                  </Button>
                  <Button
                    variant="ghost"
                    className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                    disabled={!selectedQuizId || !!questionsLoadingQuizId}
                    onClick={() => void loadQuestionsForQuiz(selectedQuizId)}
                  >
                    {questionsLoadingQuizId === selectedQuizId ? "..." : "ОБНОВИТЬ"}
                  </Button>
                </div>
              </div>

              <div className="mt-5">
                {!selectedQuizId ? (
                  <div className="py-20 text-center text-[10px] font-black uppercase tracking-widest text-zinc-400">
                    Выберите урок или тест
                  </div>
                ) : questionsLoadingQuizId === selectedQuizId && (!selectedQuizQuestions || selectedQuizQuestions.length === 0) ? (
                  <div className="py-20 text-center text-[10px] font-black uppercase tracking-widest text-zinc-400">
                    Загрузка вопросов...
                  </div>
                ) : (
                  <div className="space-y-4 max-h-[800px] overflow-auto pr-2">
                    {(selectedQuizQuestions || []).map((q: any, idx: number) => {
                      const dirty = isQuestionDirty(q);
                      const saving = questionSavingId === String(q.id);
                      return (
                        <div key={q.id} className="rounded-[24px] border border-zinc-200 bg-white p-6 shadow-sm">
                          <div className="flex items-center justify-between gap-4 mb-4">
                            <div className="flex items-center gap-3">
                              <div className="h-7 w-7 rounded-full bg-zinc-950 text-white flex items-center justify-center text-[10px] font-black">
                                {idx + 1}
                              </div>
                              <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">
                                ID: {String(q.id).slice(0, 8)}
                              </div>
                            </div>
                            <div className="flex items-center gap-2">
                              {dirty && (
                                <Button
                                  variant="primary"
                                  className="h-8 rounded-lg px-3 text-[9px] font-black uppercase tracking-widest"
                                  disabled={saving}
                                  onClick={() => void saveQuestionDraft(String(q.id))}
                                >
                                  {saving ? "..." : "СОХРАНИТЬ"}
                                </Button>
                              )}
                              <button
                                type="button"
                                className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50"
                                onClick={() => void copy(String(q.id))}
                              >
                                COPY
                              </button>
                              <button
                                type="button"
                                className="rounded-xl border border-rose-100 bg-rose-50/50 px-3 py-2 text-[9px] font-black uppercase tracking-widest text-rose-600 hover:bg-rose-100"
                                onClick={() => void deleteQuestionAdmin(String(q.id))}
                              >
                                УДАЛИТЬ
                              </button>
                            </div>
                          </div>

                          <div className="space-y-4">
                            <div>
                              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-400 mb-1.5 ml-1">Текст вопроса</div>
                              <textarea
                                className="w-full min-h-[100px] rounded-2xl border border-zinc-200 bg-zinc-50/30 p-4 text-[13px] font-medium leading-relaxed text-zinc-900 focus:border-[#fe9900]/30 focus:bg-white focus:outline-none transition-all"
                                value={getDraftValue(q, "prompt")}
                                onChange={(e) => setQuestionDraftsById(prev => ({ ...prev, [String(q.id)]: { ...prev[String(q.id)], prompt: e.target.value } }))}
                              />
                            </div>

                            <div className="grid gap-4 sm:grid-cols-2">
                              <div>
                                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-400 mb-1.5 ml-1">Верный ответ (A, B, C, D)</div>
                                <input
                                  className="w-full h-11 rounded-xl border border-zinc-200 bg-zinc-50/30 px-4 text-[13px] font-black uppercase tracking-widest text-zinc-950 focus:border-[#fe9900]/30 focus:bg-white focus:outline-none transition-all"
                                  value={getDraftValue(q, "correct_answer")}
                                  onChange={(e) => setQuestionDraftsById(prev => ({ ...prev, [String(q.id)]: { ...prev[String(q.id)], correct_answer: e.target.value } }))}
                                />
                              </div>
                              <div>
                                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-400 mb-1.5 ml-1">Тип</div>
                                <select
                                  className="w-full h-11 rounded-xl border border-zinc-200 bg-zinc-50/30 px-4 text-[11px] font-black uppercase tracking-widest text-zinc-950 focus:border-[#fe9900]/30 focus:bg-white focus:outline-none transition-all"
                                  value={getDraftValue(q, "type")}
                                  onChange={(e) => setQuestionDraftsById(prev => ({ ...prev, [String(q.id)]: { ...prev[String(q.id)], type: e.target.value } }))}
                                >
                                  <option value="single">SINGLE</option>
                                  <option value="multi">MULTI</option>
                                  <option value="case">CASE</option>
                                </select>
                              </div>
                            </div>

                            <div>
                              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-400 mb-1.5 ml-1">Пояснение</div>
                              <input
                                className="w-full h-11 rounded-xl border border-zinc-200 bg-zinc-50/30 px-4 text-[12px] font-medium text-zinc-900 focus:border-[#fe9900]/30 focus:bg-white focus:outline-none transition-all"
                                value={getDraftValue(q, "explanation") || ""}
                                onChange={(e) => setQuestionDraftsById(prev => ({ ...prev, [String(q.id)]: { ...prev[String(q.id)], explanation: e.target.value } }))}
                                placeholder="Почему этот ответ верный?"
                              />
                            </div>
                          </div>
                        </div>
                      );
                    })}
                    {(selectedQuizQuestions || []).length === 0 && (
                      <div className="py-20 text-center text-[10px] font-black uppercase tracking-widest text-zinc-400 bg-zinc-50/50 rounded-[32px] border border-dashed border-zinc-200">
                        В этом тесте пока нет вопросов
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
