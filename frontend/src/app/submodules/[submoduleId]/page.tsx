"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, File, FileImage, FileSpreadsheet, FileText, FileVideo } from "lucide-react";

import { AppShell } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { LockIcon } from "@/components/ui/lock";

type SubmoduleMeta = {
  id: string;
  module_id: string;
  title: string;
  content: string;
  order: number;
  quiz_id: string;
  requires_quiz?: boolean;
};

function decodeLegacyPercentUnicode(input: string): string {
  const raw = String(input || "").trim();
  if (!raw) return "";
  try {
    const replaced = raw.replace(/%[uU]([0-9a-fA-F]{4})/g, (_, hex) => {
      try {
        return String.fromCharCode(Number.parseInt(hex, 16));
      } catch {
        return _;
      }
    });
    const decoded = decodeURIComponent(replaced);
    return decoded.normalize("NFC");
  } catch {
    try {
      return raw.normalize("NFC");
    } catch {
      return raw;
    }
  }
}

function normalizeOptionLabel(ch: string): string | null {
  const c = String(ch || "").trim().toUpperCase();
  const map: Record<string, string> = { "А": "A", "Б": "B", "В": "C", "Г": "D", "Д": "E" };
  const v = map[c] || c;
  if (!/^[A-E]$/.test(v)) return null;
  return v;
}

function extractOptionsFromPrompt(prompt: string): { stem: string[]; options: Array<{ label: string; text: string }> } {
  const lines = formatPromptLines(prompt);
  const opts: Array<{ label: string; text: string }> = [];
  const stem: string[] = [];
  for (const ln of lines) {
    const m = /^([АБВГДA-E])\)\s*(.+)$/u.exec(ln);
    if (m) {
      const label = normalizeOptionLabel(m[1]);
      if (label) {
        opts.push({ label, text: String(m[2] || "").trim() });
        continue;
      }
    }
    stem.push(ln);
  }
  return { stem, options: opts };
}

function formatPromptLines(prompt: string): string[] {
  const normalized = String(prompt || "")
    .replace(/\r\n/g, "\n")
    .replace(/\s+(?=[А-ЯA-Z]\))/g, "\n")
    .replace(/\s+(?=[А-ЯA-Z][\).])/g, "\n");

  return normalized
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);
}

type ModuleMeta = {
  id: string;
  title: string;
};

type QuizQuestion = { id: string; prompt: string; type: string };
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

type SubmoduleAsset = {
  asset_id: string;
  object_key: string;
  original_filename: string;
  mime_type: string | null;
  order: number;
};

type ModuleAsset = {
  asset_id: string;
  object_key: string;
  original_filename: string;
  mime_type: string | null;
};

type AssetLike = {
  asset_id: string;
  mime_type: string | null;
};

type InlineKind = "iframe" | "image" | "video" | "audio" | "pdf" | "text";

type InlineTextBlock = { kind: "h" | "p" | "ul" | "pre"; text?: string; items?: string[] };

export default function SubmodulePage() {
  const params = useParams<{ submoduleId: string }>();
  const search = useSearchParams();
  const submoduleId = params.submoduleId;
  const moduleId = search.get("module") || "";

  const [submodule, setSubmodule] = useState<SubmoduleMeta | null>(null);
  const [moduleMeta, setModuleMeta] = useState<ModuleMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [moduleProgress, setModuleProgress] = useState<{
    passed: number;
    total: number;
    submodules?: Array<{
      submodule_id: string;
      order?: number;
      passed: boolean;
      best_score: number | null;
      last_score?: number | null;
      last_passed?: boolean | null;
      locked?: boolean;
    }>;
  } | null>(null);
  
  const [readConfirmed, setReadConfirmed] = useState<boolean>(false);
  const [isQuizActive, setIsQuizActive] = useState(false);
  const [isStartingQuiz, setIsStartingQuiz] = useState(false);
  const [quizData, setQuizData] = useState<QuizStart | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [quizResult, setQuizResult] = useState<QuizSubmit | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [submoduleAssets, setSubmoduleAssets] = useState<SubmoduleAsset[]>([]);
  const [moduleAssets, setModuleAssets] = useState<ModuleAsset[]>([]);
  const [inlineUrl, setInlineUrl] = useState<string | null>(null);
  const [inlineMime, setInlineMime] = useState<string | null>(null);
  const [inlineName, setInlineName] = useState<string | null>(null);
  const [inlineText, setInlineText] = useState<string | null>(null);
  const [inlineKind, setInlineKind] = useState<InlineKind>("iframe");

  const resultRef = useRef<HTMLDivElement | null>(null);
  const inlineRef = useRef<HTMLDivElement | null>(null);

  const canInlinePreview = useMemo(() => {
    const mime = String(inlineMime || "").toLowerCase();
    if (!inlineUrl) return false;
    if (!mime) return false;
    if (mime.includes("pdf")) return true;
    if (mime.startsWith("image/")) return true;
    if (mime.startsWith("video/")) return true;
    if (mime.startsWith("audio/")) return true;
    if (mime.startsWith("text/")) return true;
    return false;
  }, [inlineMime, inlineUrl]);

  const requiresQuiz = useMemo(() => {
    const v = (submodule as any)?.requires_quiz;
    if (typeof v === "boolean") return v;
    return true;
  }, [submodule]);

  function closeInline() {
    setInlineUrl(null);
    setInlineMime(null);
    setInlineName(null);
    setInlineText(null);
    setInlineKind("iframe");
  }

  function getExtFromName(name: string): string {
    const raw = String(name || "").trim();
    const m = /\.([a-z0-9]{1,8})$/i.exec(raw);
    return m ? String(m[1] || "").toLowerCase() : "";
  }

  const inlineTextBlocks = useMemo<InlineTextBlock[]>(() => {
    const raw = String(inlineText || "").replace(/\r\n/g, "\n").trim();
    if (!raw) return [];

    const isMd = getExtFromName(String(inlineName || "")) === "md";
    if (!isMd) {
      const shortened = raw.length > 15000 ? raw.slice(0, 15000) + "\n\n…" : raw;
      return [{ kind: "pre", text: shortened }];
    }

    const lines = raw.split("\n");
    const blocks: InlineTextBlock[] = [];
    let paragraph: string[] = [];
    let list: string[] = [];
    const flushParagraph = () => {
      const t = paragraph.join(" ").replace(/\s+/g, " ").trim();
      paragraph = [];
      if (t) blocks.push({ kind: "p", text: t });
    };
    const flushList = () => {
      const items = list.map((x) => x.trim()).filter(Boolean);
      list = [];
      if (items.length) blocks.push({ kind: "ul", items });
    };

    for (const lnRaw of lines) {
      const ln = String(lnRaw || "").trim();
      if (!ln) {
        flushList();
        flushParagraph();
        continue;
      }

      const h = /^(#{1,6})\s+(.+)$/.exec(ln);
      if (h) {
        flushList();
        flushParagraph();
        blocks.push({ kind: "h", text: String(h[2] || "").trim() });
        continue;
      }

      const isList = /^(-|•|\*)\s+/.test(ln) || /^\d{1,3}[.)]\s+/.test(ln);
      if (isList) {
        flushParagraph();
        list.push(ln.replace(/^(-|•|\*)\s+/, "").replace(/^\d{1,3}[.)]\s+/, "").trim());
        continue;
      }

      flushList();
      paragraph.push(ln);
    }

    flushList();
    flushParagraph();
    return blocks;
  }, [inlineName, inlineText]);

  function displayAssetTitle(name: string): string {
    const raw = decodeLegacyPercentUnicode(String(name || "").trim());
    return raw
      .replace(/^\s*\d{1,3}\s*[\.)]\s*/u, "")
      .replace(/^\s*\d{1,3}\s*[-_:]\s*/u, "")
      .trim();
  }

  const fetchData = async () => {
    try {
      setError(null);
      await apiFetch(`/submodules/${submoduleId}/open`, { method: "POST" });
      const meta = await apiFetch<SubmoduleMeta>(`/submodules/${submoduleId}`);
      setSubmodule(meta);

      const sa = await apiFetch<{ submodule_id: string; assets: SubmoduleAsset[] }>(
        `/modules/submodules/${submoduleId}/assets`
      );
      setSubmoduleAssets(Array.isArray((sa as any)?.assets) ? ((sa as any).assets as any) : []);

      const effectiveModuleId = String(moduleId || meta?.module_id || "").trim();
      if (effectiveModuleId) {
        const ma = await apiFetch<{ module_id: string; assets: ModuleAsset[] }>(
          `/modules/${effectiveModuleId}/assets`
        );
        setModuleAssets(ma.assets || []);
      } else {
        setModuleAssets([]);
      }
      
      const rs = await apiFetch<{ read: boolean }>(`/submodules/${submoduleId}/read-status`);
      setReadConfirmed(Boolean(rs.read));

      if (effectiveModuleId) {
        const mm = await apiFetch<ModuleMeta>(`/modules/${effectiveModuleId}`);
        setModuleMeta(mm);
        const prog = await apiFetch<any>(`/progress/modules/${effectiveModuleId}`);
        setModuleProgress(prog);
      }
    } catch (e) {
      const anyErr = e as any;
      const msg = e instanceof Error ? e.message : String(e);
      const rid = String(anyErr?.requestId || anyErr?.request_id || "").trim();
      setError((msg || "Не удалось загрузить данные урока") + (rid ? ` (код: ${rid})` : ""));
    }
  };

  async function presign(assetId: string, action: "view" | "download") {
    const data = await apiFetch<{ asset_id: string; download_url: string }>(
      `/assets/${assetId}/presign-download?action=${encodeURIComponent(action)}`
    );
    return data.download_url;
  }

  async function onOpenInline(a: AssetLike) {
    try {
      const url = await presign(a.asset_id, "view");
      setInlineUrl(url);
      setInlineMime(a.mime_type || null);
      const anyA = a as any;
      const nm = String(anyA?.original_filename || anyA?.name || "").trim();
      setInlineName(nm || null);

      const mime = String(a.mime_type || "").toLowerCase();
      const ext = getExtFromName(nm);

      const kind: InlineKind =
        mime.includes("pdf") || ext === "pdf"
          ? "pdf"
          : mime.startsWith("audio/") || ["mp3", "wav", "ogg", "m4a"].includes(ext)
            ? "audio"
            : mime.startsWith("video/") || ["mp4", "webm"].includes(ext)
          ? "video"
          : mime.startsWith("image/") || ["png", "jpg", "jpeg", "webp", "gif"].includes(ext)
            ? "image"
            : mime.startsWith("text/") || ["txt", "md"].includes(ext)
              ? "text"
              : "iframe";
      setInlineKind(kind);

      if (kind === "text") {
        try {
          const resp = await fetch(url, { method: "GET" });
          const txt = await resp.text();
          setInlineText(txt || "");
        } catch {
          setInlineText(null);
        }
      } else {
        setInlineText(null);
      }

      try {
        window.setTimeout(() => {
          try {
            inlineRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
          } catch {
            // ignore
          }
        }, 50);
      } catch {
        // ignore
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("corelms:toast", {
            detail: {
              title: "НЕ УДАЛОСЬ ОТКРЫТЬ ФАЙЛ",
              description: msg || "Проверьте доступ к хранилищу и попробуйте снова",
            },
          })
        );
      }
    }
  }

  async function onDownload(a: AssetLike) {
    try {
      const url = await presign(a.asset_id, "download");
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("corelms:toast", {
            detail: {
              title: "НЕ УДАЛОСЬ СКАЧАТЬ ФАЙЛ",
              description: msg || "Проверьте доступ к хранилищу и попробуйте снова",
            },
          })
        );
      }
    }
  }

  useEffect(() => {
    fetchData();
  }, [submoduleId, moduleId]);

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (!isQuizActive) return;
      e.preventDefault();
      e.returnValue = "";
    };

    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isQuizActive]);

  const lessonMaterials = useMemo(() => {
    const items = (submoduleAssets || []).slice();
    items.sort((a, b) => Number(a.order || 0) - Number(b.order || 0));
    return items;
  }, [submoduleAssets]);

  function getAssetIcon(a: { original_filename: string; mime_type: string | null }) {
    const name = String(a?.original_filename || "").toLowerCase();
    const mime = String(a?.mime_type || "").toLowerCase();
    const ext = (() => {
      const m = /\.([a-z0-9]{1,8})$/i.exec(name);
      return m ? String(m[1] || "").toLowerCase() : "";
    })();

    if (mime.startsWith("video/") || ext === "mp4" || ext === "webm") return FileVideo;
    if (mime.includes("pdf") || ext === "pdf") return FileText;
    if (mime.startsWith("image/") || ["png", "jpg", "jpeg", "webp", "gif"].includes(ext)) return FileImage;
    if (["xlsx", "xls", "csv"].includes(ext) || mime.includes("spreadsheet")) return FileSpreadsheet;
    if (["docx", "doc", "pptx", "ppt", "txt", "md"].includes(ext) || mime.startsWith("text/")) return FileText;
    return File;
  }

  const thisQuizPassed = useMemo(() => {
    const subs = moduleProgress?.submodules || [];
    const row = subs.find((s) => s.submodule_id === submoduleId);
    return Boolean(row?.passed);
  }, [moduleProgress, submoduleId]);

  const thisLastQuizScore = useMemo(() => {
    const subs = moduleProgress?.submodules || [];
    const row = subs.find((s) => s.submodule_id === submoduleId);
    const v = row?.last_score;
    return typeof v === "number" ? v : null;
  }, [moduleProgress, submoduleId]);

  const thisLastQuizPassed = useMemo(() => {
    const subs = moduleProgress?.submodules || [];
    const row = subs.find((s) => s.submodule_id === submoduleId);
    const v = row?.last_passed;
    return typeof v === "boolean" ? v : null;
  }, [moduleProgress, submoduleId]);

  const hasQuizAttempt = useMemo(() => {
    const subs = moduleProgress?.submodules || [];
    const row = subs.find((s) => s.submodule_id === submoduleId);
    const scorePresent = row?.last_score !== undefined && row?.last_score !== null;
    const passedPresent = row?.last_passed !== undefined && row?.last_passed !== null;
    return Boolean(scorePresent || passedPresent);
  }, [moduleProgress, submoduleId]);

  const displayLastQuizScore = useMemo(() => {
    if (!hasQuizAttempt) return null;
    return typeof thisLastQuizScore === "number" ? thisLastQuizScore : 0;
  }, [hasQuizAttempt, thisLastQuizScore]);

  const nextSubmoduleId = useMemo(() => {
    const subs = (moduleProgress?.submodules || []).slice();
    if (!subs.length) return "";
    subs.sort((a, b) => Number(a.order || 0) - Number(b.order || 0));
    const idx = subs.findIndex((s) => String(s.submodule_id) === String(submoduleId));
    if (idx < 0) return "";
    for (let i = idx + 1; i < subs.length; i++) {
      const s = subs[i];
      if (s && !s.locked) return String(s.submodule_id || "");
    }
    return "";
  }, [moduleProgress, submoduleId]);

  const theoryDotClass = useMemo(() => {
    return readConfirmed
      ? "bg-[#284e13] shadow-[0_0_8px_rgba(40,78,19,0.25)]"
      : "bg-zinc-600";
  }, [readConfirmed]);

  const quizDotClass = useMemo(() => {
    if (!requiresQuiz) return "bg-zinc-300";
    if (thisQuizPassed) return "bg-[#284e13] shadow-[0_0_8px_rgba(40,78,19,0.25)]";
    if (hasQuizAttempt) return "bg-rose-400 shadow-[0_0_8px_rgba(251,113,133,0.35)]";
    return "bg-zinc-600";
  }, [hasQuizAttempt, requiresQuiz, thisQuizPassed]);

  const quizTotals = useMemo(() => {
    if (!moduleProgress) return { passed: 0, total: 0 };
    return { passed: moduleProgress.passed || 0, total: moduleProgress.total || 0 };
  }, [moduleProgress]);

  const answeredCount = useMemo(() => {
    if (!quizData) return 0;
    return quizData.questions.reduce((acc, q) => acc + (answers[q.id]?.trim() ? 1 : 0), 0);
  }, [answers, quizData]);

  const canSubmit = useMemo(() => {
    if (!quizData) return false;
    return answeredCount === quizData.questions.length;
  }, [answeredCount, quizData]);

  const formatPrompt = (prompt: string) => {
    return (prompt || "")
      .replace(/\s+(?=А\))/g, "\n")
      .replace(/\s+(?=Б\))/g, "\n")
      .replace(/\s+(?=В\))/g, "\n")
      .replace(/\s+(?=Г\))/g, "\n")
      .replace(/\s+(?=Д\))/g, "\n");
  };

  const theoryBlocks = useMemo(() => {
    const raw = String(submodule?.content || "").replace(/\r\n/g, "\n").trim();
    if (!raw) return [] as Array<{ kind: "h" | "p" | "ul"; text?: string; items?: string[] }>;

    const lines = raw.split("\n");
    const blocks: Array<{ kind: "h" | "p" | "ul"; text?: string; items?: string[] }> = [];
    let paragraph: string[] = [];
    let list: string[] = [];

    const flushParagraph = () => {
      const t = paragraph.join(" ").replace(/\s+/g, " ").trim();
      paragraph = [];
      if (t) blocks.push({ kind: "p", text: t });
    };
    const flushList = () => {
      const items = list.map((x) => x.trim()).filter(Boolean);
      list = [];
      if (items.length) blocks.push({ kind: "ul", items });
    };

    for (const lnRaw of lines) {
      const ln = String(lnRaw || "").trim();

      if (!ln) {
        flushList();
        flushParagraph();
        continue;
      }

      const isList = /^(-|•|\*)\s+/.test(ln) || /^\d{1,3}[.)]\s+/.test(ln);
      if (isList) {
        flushParagraph();
        list.push(ln.replace(/^(-|•|\*)\s+/, "").replace(/^\d{1,3}[.)]\s+/, "").trim());
        continue;
      }

      const isHeading =
        ln.length <= 80 &&
        (ln.startsWith("##") || ln.startsWith("###") || /:$/.test(ln) || (/^[А-Я0-9\s-]{6,}$/.test(ln) && ln.replace(/\s/g, "").length >= 6));
      if (isHeading) {
        flushList();
        flushParagraph();
        blocks.push({ kind: "h", text: ln.replace(/^#{2,3}\s*/, "").replace(/:$/, "").trim() });
        continue;
      }

      flushList();
      paragraph.push(ln);
    }

    flushList();
    flushParagraph();
    return blocks;
  }, [submodule?.content]);

  async function onConfirmRead() {
    try {
      const resp = await apiFetch<{ ok: boolean; xp_awarded?: number }>(`/submodules/${submoduleId}/read`, { method: "POST" });
      setReadConfirmed(true);
      const xp = Number(resp?.xp_awarded || 0);
      if (xp > 0 && typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("corelms:toast", {
          detail: { title: `+${xp} XP`, description: "Теория изучена" },
        }));
      }
      window.dispatchEvent(new CustomEvent("corelms:refresh-me", { detail: { reason: "progress" } }));
    } catch (e) {
      setError("Ошибка при подтверждении прочтения");
    }
  }

  async function onStartQuiz() {
    if (isStartingQuiz) return;
    try {
      if (!requiresQuiz) {
        return;
      }
      if (!submodule?.quiz_id) {
        setError("Не удалось начать тест: quiz_id не найден");
        return;
      }
      setIsStartingQuiz(true);
      setQuizData(null);
      setIsQuizActive(true);
      setQuizResult(null);
      setAnswers({});
      const data = await apiFetch<QuizStart>(`/quizzes/${submodule?.quiz_id}/start`, { method: "POST" });
      setQuizData(data);
    } catch (e) {
      setError("Не удалось начать тест");
      setIsQuizActive(false);
    } finally {
      setIsStartingQuiz(false);
    }
  }

  async function onSubmitQuiz() {
    if (!quizData || isSubmitting) return;
    setIsSubmitting(true);
    try {
      const payload = {
        answers: quizData.questions.map((q) => ({ question_id: q.id, answer: answers[q.id] || "" })),
      };
      const result = await apiFetch<QuizSubmit>(`/quizzes/${quizData.quiz_id}/submit`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setQuizResult(result);
      setIsQuizActive(false);

      try {
        window.setTimeout(() => {
          try {
            resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
          } catch {
            // ignore
          }
        }, 50);
      } catch {
        // ignore
      }
      
      const xp = Number(result?.xp_awarded || 0);
      if (xp > 0 && typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("corelms:toast", {
          detail: { title: `+${xp} XP`, description: result.passed ? "Тест пройден" : "Попытка засчитана" },
        }));
      }
      
      await fetchData();
      window.dispatchEvent(new CustomEvent("corelms:refresh-me", { detail: { reason: "progress" } }));
    } catch (e) {
      setError("Ошибка при сдаче теста");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-6 py-12 lg:py-20">
        {error && (
          <div className="mb-10 rounded-2xl border border-rose-500/20 bg-rose-500/5 p-4 text-sm text-rose-400 font-bold uppercase tracking-widest text-center">
            {error}
          </div>
        )}
        <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-10">
          <div className="flex-1">
            <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900] mb-2">Урок курса</div>
            <h1 className="text-5xl font-black tracking-tighter text-zinc-950 uppercase leading-none">
              {moduleMeta?.title || "Загрузка..."}
            </h1>

            <div className="mt-8 max-w-xl">
              <div className="flex items-center justify-between text-[10px] font-black uppercase tracking-widest text-zinc-600 mb-2">
                <div>Прогресс модуля</div>
                <div className="tabular-nums text-[#284e13]">
                  {quizTotals.passed} / {quizTotals.total}
                </div>
              </div>
              <div className="h-1 w-full rounded-full bg-zinc-200 overflow-hidden">
                <div 
                  className="h-full bg-[#fe9900] transition-all duration-1000"
                  style={{ width: `${quizTotals.total > 0 ? Math.round((quizTotals.passed / quizTotals.total) * 100) : 0}%` }}
                />
              </div>
            </div>
          </div>
          
          <Link href={`/modules/${moduleId}`}>
            <Button variant="ghost" size="sm" className="rounded-xl font-black uppercase tracking-widest text-[10px]">
              <ChevronLeft className="mr-2 h-4 w-4" />
              оглавление
            </Button>
          </Link>
        </div>

        <div className="mt-16 grid gap-10 lg:grid-cols-12 items-start">
          <div className="lg:col-span-4 space-y-6 lg:sticky lg:top-24">
            <div className="relative overflow-hidden border border-zinc-200 bg-white/70 backdrop-blur-md rounded-[28px] shadow-2xl shadow-zinc-950/10 p-8">
              <div className="absolute left-0 top-0 h-full w-[2px] bg-gradient-to-b from-[#fe9900]/40 to-transparent" />
              <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500 mb-8">Статус шага</div>
              
              <div className="space-y-4">
                <div className="flex items-center justify-between p-4 rounded-2xl bg-white border border-zinc-200">
                  <div className="flex items-center gap-3">
                    <div className={`h-2 w-2 rounded-full ${theoryDotClass}`} />
                    <span className="text-[10px] font-black uppercase tracking-widest text-zinc-700">Теория</span>
                  </div>
                  <span className={`text-[10px] font-black uppercase tracking-widest ${readConfirmed ? "text-[#284e13]" : "text-zinc-600"}`}>
                    {readConfirmed ? "ГОТОВО" : "ОЖИДАНИЕ"}
                  </span>
                </div>

                <div className="flex items-center justify-between p-4 rounded-2xl bg-white border border-zinc-200">
                  <div className="flex items-center gap-3">
                    <div className={`h-2 w-2 rounded-full ${quizDotClass}`} />
                    <span className="text-[10px] font-black uppercase tracking-widest text-zinc-700">Тест</span>
                  </div>
                  <span
                    className={`text-[10px] font-black uppercase tracking-widest ${
                      !requiresQuiz
                        ? "text-zinc-400"
                        : thisQuizPassed
                        ? "text-[#284e13]"
                        : hasQuizAttempt
                        ? "text-rose-700"
                        : "text-zinc-600"
                    }`}
                  >
                    {!requiresQuiz ? "НЕТ" : typeof displayLastQuizScore === "number" ? `${displayLastQuizScore}%` : "—"}
                  </span>
                </div>

                <div className="pt-6">
                  {!readConfirmed ? (
                    <Button className="w-full h-14 rounded-2xl font-black uppercase tracking-widest text-[10px] shadow-sm" onClick={onConfirmRead}>
                      Изучил теорию
                    </Button>
                  ) : !requiresQuiz ? (
                    <div className="rounded-2xl border border-zinc-200 bg-white p-4 text-center">
                      <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600">
                        Этот урок без теста
                      </div>
                      {moduleId && nextSubmoduleId ? (
                        <div className="mt-4">
                          <Link href={`/submodules/${encodeURIComponent(nextSubmoduleId)}?module=${encodeURIComponent(moduleId)}`} className="block">
                            <Button className="w-full h-12 rounded-xl font-black uppercase tracking-widest text-[10px]">
                              Следующий урок
                            </Button>
                          </Link>
                        </div>
                      ) : null}
                    </div>
                  ) : !isQuizActive ? (
                    <Button
                      className="w-full h-14 rounded-2xl font-black uppercase tracking-widest text-[10px] shadow-sm"
                      onClick={onStartQuiz}
                      disabled={isStartingQuiz}
                    >
                      {thisQuizPassed ? "Пересдать тест" : "Начать тест"}
                    </Button>
                  ) : (
                    <div className="rounded-2xl border border-zinc-200 bg-white p-4">
                      <div className="flex items-center justify-between text-[10px] font-black uppercase tracking-widest text-zinc-600">
                        <span>Прогресс</span>
                        <span className="tabular-nums text-[#284e13]">{answeredCount} / {quizData?.questions.length || 0}</span>
                      </div>
                      <div className="mt-3 h-1 w-full overflow-hidden rounded-full bg-zinc-200">
                        <div
                          className="h-full bg-[#fe9900] transition-all duration-500"
                          style={{
                            width: `${quizData?.questions.length ? Math.round((answeredCount / quizData.questions.length) * 100) : 0}%`,
                          }}
                        />
                      </div>

                      <div className="mt-6 grid gap-2">
                        <Button
                          className="w-full h-12 rounded-xl font-black uppercase tracking-widest text-[10px]"
                          onClick={onSubmitQuiz}
                          disabled={isSubmitting || !canSubmit}
                        >
                          {isSubmitting ? "Отправка..." : "Сдать"}
                        </Button>
                        <Button variant="ghost" className="w-full h-12 rounded-xl font-black uppercase tracking-widest text-[10px]" onClick={() => setIsQuizActive(false)}>
                          Отмена
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {(quizResult || typeof thisLastQuizScore === "number") && !isQuizActive && (
                <div
                  ref={resultRef}
                  className={
                    "mt-6 p-6 rounded-2xl border animate-in fade-in slide-in-from-top-2 duration-300 " +
                    ((quizResult?.passed ?? thisLastQuizPassed)
                      ? "border-[#284e13]/20 bg-[#284e13]/5"
                      : "border-rose-500/20 bg-rose-500/5")
                  }
                >
                  <div className="flex items-center justify-between mb-4">
                    <span
                      className={
                        "text-[10px] font-black uppercase tracking-widest " +
                        ((quizResult?.passed ?? thisLastQuizPassed) ? "text-[#284e13]" : "text-rose-700")
                      }
                    >
                      {(quizResult?.passed ?? thisLastQuizPassed) ? "ЗАЧЁТ" : "НЕ ЗАЧЁТ"}
                    </span>
                    <span
                      className={
                        "text-3xl font-black " + ((quizResult?.passed ?? thisLastQuizPassed) ? "text-[#284e13]" : "text-rose-700")
                      }
                    >
                      {quizResult ? `${quizResult.score}%` : `${thisLastQuizScore}%`}
                    </span>
                  </div>
                  <div className="text-xs text-zinc-500 font-medium leading-relaxed">
                    {quizResult
                      ? `${quizResult.correct} из ${quizResult.total} правильных. ${quizResult.passed ? "Отличная работа!" : "Нужно минимум 70%."}`
                      : (thisLastQuizPassed ? "Результат засчитан. Можно идти дальше." : "Результат не засчитан. Попробуй еще раз.")}
                  </div>

                  {moduleId && nextSubmoduleId ? (
                    <div className="mt-5">
                      <Link href={`/submodules/${encodeURIComponent(nextSubmoduleId)}?module=${encodeURIComponent(moduleId)}`} className="block">
                        <Button className="w-full h-12 rounded-xl font-black uppercase tracking-widest text-[10px]">
                          Следующий урок
                        </Button>
                      </Link>
                    </div>
                  ) : null}
                </div>
              )}
            </div>

            <div className="relative overflow-hidden border border-zinc-200 bg-white/70 backdrop-blur-md rounded-[28px] shadow-2xl shadow-zinc-950/10 p-8">
              <div className="absolute left-0 top-0 h-full w-[2px] bg-gradient-to-b from-[#fe9900]/40 to-transparent" />
              <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500 mb-8">Материалы модуля</div>

              {!moduleAssets.length ? (
                <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600 py-10 text-center border border-dashed border-zinc-200 rounded-2xl">
                  Нет файлов
                </div>
              ) : (
                <div className="grid gap-3">
                  {moduleAssets.map((a, idx) => (
                      <div
                        key={a.asset_id}
                        className="group relative overflow-hidden rounded-2xl border border-zinc-200 bg-white/70 p-4 transition-all duration-300 hover:bg-white"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex items-center gap-3 min-w-0">
                              <span className="shrink-0 text-[10px] font-black uppercase tracking-widest text-zinc-500 tabular-nums">
                                {String(idx + 1).padStart(2, "0")}
                              </span>
                              <div className="min-w-0 truncate text-sm font-bold text-zinc-950 transition-colors">
                                {displayAssetTitle(a.original_filename || "ФАЙЛ")}
                              </div>
                            </div>
                          </div>
                        </div>

                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() => void onOpenInline(a)}
                            className="rounded-xl bg-[#fe9900]/10 border border-[#fe9900]/25 px-3 py-2 text-[9px] font-black text-[#284e13] uppercase tracking-widest hover:bg-[#fe9900] hover:text-zinc-950 transition-all active:scale-95"
                          >
                            просмотр
                          </button>
                          <button
                            type="button"
                            onClick={() => void onDownload(a)}
                            className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50 transition-all active:scale-95"
                          >
                            скачать
                          </button>
                        </div>
                      </div>
                    ))}
                </div>
              )}
            </div>
          </div>

          <div className="lg:col-span-8 space-y-10">
            {!isQuizActive ? (
              <div className="relative group overflow-hidden rounded-[32px] border border-zinc-200 bg-white/70 backdrop-blur-md p-10 lg:p-12 shadow-2xl shadow-zinc-950/10 transition-all duration-300 hover:bg-white">
                <div className="absolute top-0 left-0 h-full w-[4px] bg-[#fe9900] opacity-20" />
                <div className="flex items-center gap-6 mb-12">
                  <div className="rounded-2xl border border-[#fe9900]/25 bg-[#fe9900]/10 px-4 py-3 text-3xl font-black text-zinc-950 tabular-nums uppercase leading-none">
                    #{String(submodule?.order).padStart(2, '0')}
                  </div>
                  <div className="min-w-0">
                    <h2 className="text-4xl font-black text-zinc-950 uppercase tracking-tighter leading-tight break-words">
                      {submodule?.title}
                    </h2>
                  </div>
                </div>

                {inlineUrl ? (
                  <div ref={inlineRef} className="mb-10 rounded-[24px] border border-zinc-200 bg-white p-6 shadow-sm">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">
                        Просмотр файла{inlineName ? `: ${displayAssetTitle(inlineName)}` : ""}
                      </div>
                      <button
                        type="button"
                        onClick={closeInline}
                        className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50 transition-all active:scale-95"
                      >
                        закрыть
                      </button>
                    </div>

                    {canInlinePreview ? (
                      <div className="mt-4 overflow-hidden rounded-2xl border border-zinc-200 bg-white">
                        {inlineKind === "video" ? (
                          <video src={inlineUrl} controls className="w-full h-auto bg-black" preload="metadata" />
                        ) : inlineKind === "audio" ? (
                          <div className="p-4">
                            <audio src={inlineUrl} controls className="w-full" preload="metadata" />
                          </div>
                        ) : inlineKind === "pdf" ? (
                          <iframe
                            src={inlineUrl}
                            className="w-full h-[640px]"
                            sandbox="allow-same-origin allow-scripts allow-forms"
                            title={String(inlineName || "PDF")}
                          />
                        ) : inlineKind === "image" ? (
                          <img src={inlineUrl} alt="" className="w-full h-auto" />
                        ) : inlineKind === "text" ? (
                          <div className="p-4">
                            {!inlineTextBlocks.length ? (
                              <div className="text-xs text-zinc-600 font-medium">Не удалось загрузить текст для предпросмотра.</div>
                            ) : (
                              <div className="space-y-4">
                                {inlineTextBlocks.map((b, idx) =>
                                  b.kind === "h" ? (
                                    <div key={idx} className="text-sm font-black uppercase tracking-widest text-zinc-900">
                                      {b.text}
                                    </div>
                                  ) : b.kind === "ul" ? (
                                    <ul key={idx} className="list-disc pl-5 text-sm text-zinc-800 font-medium space-y-1">
                                      {(b.items || []).map((it, j) => (
                                        <li key={j}>{it}</li>
                                      ))}
                                    </ul>
                                  ) : b.kind === "pre" ? (
                                    <pre key={idx} className="whitespace-pre-wrap text-xs text-zinc-800 font-mono">
                                      {b.text}
                                    </pre>
                                  ) : (
                                    <div key={idx} className="text-sm text-zinc-800 font-medium leading-relaxed">
                                      {b.text}
                                    </div>
                                  )
                                )}
                              </div>
                            )}
                          </div>
                        ) : (
                          <iframe
                            src={inlineUrl}
                            className="w-full h-[520px]"
                            sandbox="allow-same-origin allow-scripts allow-forms"
                            title={String(inlineName || "Файл")}
                          />
                        )}
                      </div>
                    ) : inlineUrl ? (
                      <div className="mt-4 rounded-2xl border border-zinc-200 bg-white p-4">
                        <div className="text-[10px] font-black uppercase tracking-widest text-zinc-600">ПРЕДПРОСМОТР НЕДОСТУПЕН</div>
                        <div className="mt-2 text-[11px] font-bold text-zinc-800">
                          Этот формат лучше скачать и открыть локально (например, Excel/PowerPoint/Word).
                        </div>
                      </div>
                    ) : null}
                    <div className="mt-4 rounded-2xl border border-zinc-200 bg-zinc-50 p-4">
                      <div className="text-[10px] font-black uppercase tracking-widest text-zinc-700">Этот формат не поддерживает просмотр</div>
                      <div className="mt-2 text-xs text-zinc-600 font-medium">Используйте кнопку “скачать” в списке материалов.</div>
                    </div>
                  </div>
                ) : null}
                
                {lessonMaterials.length ? (
                  <div className="mb-10 rounded-[24px] border border-zinc-200 bg-white p-6">
                    <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Материалы урока</div>
                    <div className="mt-4 grid gap-3">
                      {lessonMaterials.map((a) => {
                        const Icon = getAssetIcon(a);
                        return (
                          <div
                            key={a.asset_id}
                            className="group/material flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-zinc-200 bg-zinc-50 p-4"
                          >
                            <div className="min-w-0 flex items-center gap-3">
                              <Icon className="h-4 w-4 text-zinc-500 shrink-0" />
                              <div className="min-w-0">
                                <div className="text-sm font-bold text-zinc-900 truncate">
                                  {displayAssetTitle(a.original_filename || "ФАЙЛ")}
                                </div>
                                <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500 truncate">
                                  {decodeLegacyPercentUnicode(a.original_filename || "")}
                                </div>
                              </div>
                            </div>

                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() => void onOpenInline(a)}
                                className="rounded-xl bg-[#fe9900]/10 border border-[#fe9900]/25 px-3 py-2 text-[9px] font-black text-[#284e13] uppercase tracking-widest hover:bg-[#fe9900] hover:text-zinc-950 transition-all active:scale-95"
                              >
                                просмотр
                              </button>
                              <button
                                type="button"
                                onClick={() => void onDownload(a)}
                                className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50 transition-all active:scale-95"
                              >
                                скачать
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : null}

                <div className="prose max-w-none">
                  {theoryBlocks.length === 0 ? (
                    moduleAssets.length > 0 ? (
                      <div className="rounded-[24px] border border-zinc-200 bg-white p-6">
                        <div className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Материалы урока</div>
                        <div className="mt-2 text-sm font-bold text-zinc-700">
                          У этого модуля нет отдельных уроков с текстовой теорией. Материалы доступны файлами ниже.
                        </div>
                        <div className="mt-4 grid gap-3">
                          {moduleAssets.map((a, idx) => (
                            <div
                              key={a.asset_id}
                              className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-zinc-200 bg-zinc-50 p-4"
                            >
                              <div className="min-w-0">
                                <div className="flex items-center gap-3 min-w-0">
                                  <span className="shrink-0 text-[10px] font-black uppercase tracking-widest text-zinc-500 tabular-nums">
                                    {String(idx + 1).padStart(2, "0")}
                                  </span>
                                  <div className="min-w-0 truncate text-[11px] font-black text-zinc-950 uppercase tracking-widest">
                                    {displayAssetTitle((a as any).original_filename || "ФАЙЛ")}
                                  </div>
                                </div>
                              </div>
                              <div className="flex items-center gap-2">
                                <button
                                  type="button"
                                  onClick={() => void onOpenInline(a as any)}
                                  className="rounded-xl bg-[#fe9900]/10 border border-[#fe9900]/25 px-3 py-2 text-[9px] font-black text-[#284e13] uppercase tracking-widest hover:bg-[#fe9900] hover:text-zinc-950 transition-all active:scale-95"
                                >
                                  просмотр
                                </button>
                                <button
                                  type="button"
                                  onClick={() => void onDownload(a as any)}
                                  className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-[9px] font-black uppercase tracking-widest text-zinc-700 hover:bg-zinc-50 transition-all active:scale-95"
                                >
                                  скачать
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <div className="whitespace-pre-wrap leading-relaxed text-zinc-700 text-base font-medium selection:bg-[#fe9900]/25">
                        {submodule?.content || "Загрузка контента..."}
                      </div>
                    )
                  ) : (
                    <div className="space-y-6">
                      {theoryBlocks.map((b, idx) =>
                        b.kind === "h" ? (
                          <div key={idx} className="pt-2">
                            <div className="text-[10px] font-black uppercase tracking-[0.3em] text-[#fe9900]">Раздел</div>
                            <div className="mt-2 text-2xl font-black tracking-tight text-zinc-950">{b.text}</div>
                          </div>
                        ) : b.kind === "ul" ? (
                          <div key={idx} className="rounded-[24px] border border-zinc-200 bg-white p-6">
                            <div className="grid gap-3">
                              {(b.items || []).map((it, i) => (
                                <div key={i} className="flex items-start gap-3">
                                  <div className="mt-1.5 h-2 w-2 rounded-full bg-[#fe9900]/70 shadow-[0_0_10px_rgba(254,153,0,0.18)]" />
                                  <div className="min-w-0 text-zinc-700 text-base leading-relaxed">{it}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : (
                          <div key={idx} className="text-zinc-700 text-base leading-relaxed">
                            {b.text}
                          </div>
                        )
                      )}
                    </div>
                  )}
                </div>
              </div>
            ) : !quizData ? (
              <div className="rounded-[32px] border border-zinc-200 bg-white/70 p-20 animate-in fade-in zoom-in-95 duration-500 text-center shadow-2xl shadow-zinc-950/10">
                <div className="inline-flex items-center gap-3 px-4 py-2 rounded-full bg-[#fe9900]/10 border border-[#fe9900]/20 mb-8">
                  <div className="h-2 w-2 rounded-full bg-[#fe9900] animate-pulse" />
                  <span className="text-[10px] font-black text-[#fe9900] uppercase tracking-widest">Подготовка теста</span>
                </div>
                <h3 className="text-3xl font-black text-zinc-950 uppercase tracking-tighter mb-10">Подготавливаем вопросы</h3>
                <div className="h-1 w-full max-w-xs mx-auto rounded-full bg-zinc-200 overflow-hidden">
                  <div className="h-full w-1/2 bg-[#fe9900] animate-[loading_2s_ease-in-out_infinite]" />
                </div>
              </div>
            ) : (
              <div className="space-y-10">
                <div className="rounded-[32px] border border-zinc-200 bg-white/70 p-10 lg:p-16 animate-in fade-in zoom-in-95 duration-500 shadow-2xl shadow-zinc-950/10">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-8 mb-16 border-b border-zinc-200 pb-10">
                    <div className="flex flex-col gap-3">
                      <div className="text-[10px] font-black text-[#fe9900] uppercase tracking-[0.3em]">Проверка знаний</div>
                      <h2 className="text-4xl font-black text-zinc-950 uppercase tracking-tighter leading-none">{submodule?.title}</h2>
                    </div>
                    <div className="flex items-center gap-8">
                      <div className="text-right">
                        <div className="text-[10px] font-black text-zinc-500 uppercase tracking-widest">Попытка</div>
                        <div className="text-4xl font-black text-zinc-950 tabular-nums">#{quizData.attempt_no}</div>
                      </div>
                    </div>
                  </div>

                  <div className="space-y-10">
                    {quizData.questions.map((q, idx) => {
                      const parsed = extractOptionsFromPrompt(q.prompt);
                      const selectedRaw = String(answers[q.id] || "").trim();
                      const selected = new Set(
                        selectedRaw
                          .split(",")
                          .map((x) => normalizeOptionLabel(x) || "")
                          .filter(Boolean)
                      );
                      const isMulti = String(q.type || "").toLowerCase() === "multi";

                      function setSingle(label: string) {
                        setAnswers((prev) => ({ ...prev, [q.id]: label }));
                      }

                      function toggleMulti(label: string) {
                        setAnswers((prev) => {
                          const cur = new Set(
                            String(prev[q.id] || "")
                              .split(",")
                              .map((x) => normalizeOptionLabel(x) || "")
                              .filter(Boolean)
                          );
                          if (cur.has(label)) cur.delete(label);
                          else cur.add(label);
                          const out = Array.from(cur).sort().join(",");
                          return { ...prev, [q.id]: out };
                        });
                      }

                      return (
                        <div
                          key={q.id}
                          className="group relative overflow-hidden rounded-[28px] bg-white border border-zinc-200 p-8 transition-all duration-300 hover:bg-zinc-50"
                        >
                          <div className="flex gap-8">
                            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#fe9900]/10 border border-[#fe9900]/20 text-zinc-950 text-base font-black tabular-nums">
                              {idx + 1}
                            </span>
                            <div className="flex-1">
                              <div className="text-base font-bold text-zinc-950 leading-relaxed tracking-tight mb-6 space-y-2 whitespace-pre-line">
                                {parsed.stem.map((ln, i) => (
                                  <div key={i}>{ln}</div>
                                ))}
                              </div>

                              {parsed.options.length ? (
                                <div className="grid gap-3">
                                  <div className="grid gap-2">
                                    {parsed.options.map((o) => {
                                      const active = selected.has(o.label);
                                      return (
                                        <button
                                          key={o.label}
                                          type="button"
                                          disabled={Boolean(quizResult)}
                                          onClick={() => (isMulti ? toggleMulti(o.label) : setSingle(o.label))}
                                          className={
                                            "w-full rounded-2xl border px-5 py-4 text-left transition-all active:scale-[0.99] " +
                                            (active
                                              ? "border-[#fe9900]/45 bg-[#fe9900]/10"
                                              : "border-zinc-200 bg-white hover:bg-zinc-50")
                                          }
                                        >
                                          <div className="flex items-start gap-4">
                                            <div
                                              className={
                                                "mt-0.5 flex h-9 w-9 items-center justify-center rounded-xl border text-sm font-black tabular-nums " +
                                                (active
                                                  ? "border-[#fe9900]/40 bg-[#fe9900]/20 text-zinc-950"
                                                  : "border-zinc-200 bg-white text-zinc-700")
                                              }
                                            >
                                              {o.label}
                                            </div>
                                            <div className="flex-1">
                                              <div className="text-sm font-bold text-zinc-950 leading-snug">{o.text}</div>
                                              {isMulti ? (
                                                <div className="mt-1 text-[10px] font-black uppercase tracking-widest text-zinc-500">
                                                  Нажимай для выбора нескольких
                                                </div>
                                              ) : null}
                                            </div>
                                          </div>
                                        </button>
                                      );
                                    })}
                                  </div>

                                  <div className="text-[10px] font-black text-zinc-600 uppercase tracking-widest">
                                    {isMulti ? "НЕСКОЛЬКО ВАРИАНТОВ" : "ОДИН ВАРИАНТ"}
                                  </div>
                                </div>
                              ) : (
                                <div className="grid gap-3">
                                  <input
                                    className="h-12 w-full rounded-2xl bg-white border border-zinc-200 px-6 text-base text-zinc-950 outline-none focus:border-[#fe9900]/50 focus:ring-4 focus:ring-[#fe9900]/15 transition-all placeholder:text-zinc-400 font-medium"
                                    value={answers[q.id] || ""}
                                    onChange={(e) => setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
                                    placeholder={q.type === "multi" ? "ABC..." : "Ваш ответ..."}
                                    disabled={Boolean(quizResult)}
                                  />
                                  <div className="text-[10px] font-black text-zinc-600 uppercase tracking-widest">
                                    {q.type === "multi"
                                      ? "НЕСКОЛЬКО ВАРИАНТОВ (БУКВЫ, НАПРИМЕР: A,C)"
                                      : "ОДИН ВАРИАНТ (БУКВА A/B/C/D)"}
                                  </div>
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

          </div>
        </div>
      </div>
    </AppShell>
  );
}
