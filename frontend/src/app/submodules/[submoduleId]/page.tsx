"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import { ChevronLeft, File, FileImage, FileSpreadsheet, FileText, FileVideo } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

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

type ModuleSubmoduleListItem = {
  id: string;
  module_id: string;
  title: string;
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
  original_filename: string;
  mime_type: string | null;
};

type InlineKind = "iframe" | "image" | "video" | "audio" | "pdf" | "text" | "office";

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
  const [moduleSubmodules, setModuleSubmodules] = useState<ModuleSubmoduleListItem[]>([]);
  const [assetNavPath, setAssetNavPath] = useState<string[]>([]);
  const [inlineUrl, setInlineUrl] = useState<string | null>(null);
  const [inlineMime, setInlineMime] = useState<string | null>(null);
  const [inlineName, setInlineName] = useState<string | null>(null);
  const [inlineText, setInlineText] = useState<string | null>(null);
  const [inlineAssetId, setInlineAssetId] = useState<string | null>(null);
  const [inlineKind, setInlineKind] = useState<InlineKind>("iframe");

  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isSpeakPaused, setIsSpeakPaused] = useState(false);
  const [speakRate, setSpeakRate] = useState(1.02);
  const [speakPitch, setSpeakPitch] = useState(1);
  const [speakVoiceUri, setSpeakVoiceUri] = useState<string>("");
  const [availableVoices, setAvailableVoices] = useState<Array<{ voiceURI: string; name: string; lang: string }>>([]);
  const speakActiveRef = useRef(false);

  const resultRef = useRef<HTMLDivElement | null>(null);
  const inlineRef = useRef<HTMLDivElement | null>(null);

  const canInlinePreview = useMemo(() => {
    const mime = String(inlineMime || "").toLowerCase();
    if (!inlineUrl) return false;
    if (inlineKind === "office") return true;
    if (!mime) return false;
    if (mime.includes("pdf")) return true;
    if (mime.startsWith("image/")) return true;
    if (mime.startsWith("video/")) return true;
    if (mime.startsWith("audio/")) return true;
    if (mime.startsWith("text/")) return true;
    return false;
  }, [inlineKind, inlineMime, inlineUrl]);

  const requiresQuiz = useMemo(() => {
    const v = (submodule as any)?.requires_quiz;
    if (typeof v === "boolean") return v;
    return true;
  }, [submodule]);

  const isFileLesson = useMemo(() => {
    return !requiresQuiz;
  }, [requiresQuiz]);

  const normalizeTheoryText = (raw: string): string => {
    try {
      let s = String(raw || "").replace(/\r\n/g, "\n");
      // If the content is pasted as a single paragraph with inline numbering,
      // convert common patterns into line breaks so list parsing becomes consistent.
      // Examples:
      // ". 1 - item 2 - item" -> ".\n1 - item\n2 - item"
      s = s.replace(/([.!?])\s+(\d{1,3})\s*[-—]\s+/g, "$1\n$2 - ");
      s = s.replace(/([.!?])\s+(\d{1,3})\s*[.)]\s+/g, "$1\n$2) ");
      s = s.replace(/\n\s*(\d{1,3})\s*[-—]\s+/g, "\n$1 - ");
      s = s.replace(/\n\s*(\d{1,3})\s*[.)]\s+/g, "\n$1) ");
      s = s.replace(/\s{2,}(\d{1,3})\s*[-—]\s+/g, "\n$1 - ");
      s = s.replace(/\s{2,}(\d{1,3})\s*[.)]\s+/g, "\n$1) ");
      return s;
    } catch {
      return String(raw || "");
    }
  };

  const lessonMarkdownForDisplay = useMemo(() => {
    try {
      const raw = String(submodule?.content || "");
      if (!raw.trim()) return raw;

      const src = normalizeTheoryText(raw)
        .replace(/\r\n/g, "\n")
        .replace(/\s+\n/g, "\n")
        .replace(/\n{3,}/g, "\n\n");

      const src2 = src
        .split("\n")
        .map((ln) => {
          const s = String(ln || "");
          const m = /^\s*(\d{1,3})\s*[-—]\s+(.+)$/u.exec(s);
          if (m) return `${m[1]}. ${m[2]}`;
          return s;
        })
        .join("\n");

      const lines = src2.split("\n");
      const out: string[] = [];

      const isNumberOnly = (ln: string) => /^\s*\d{1,3}\.\s*$/.test(String(ln || ""));

      for (let i = 0; i < lines.length; i++) {
        const ln = String(lines[i] || "");
        if (!isNumberOnly(ln)) {
          out.push(ln);
          continue;
        }

        const num = String(ln).trim().replace(/\.$/, "");

        let j = i + 1;
        while (j < lines.length && !String(lines[j] || "").trim()) j += 1;

        const chunk: string[] = [];
        while (j < lines.length) {
          const t = String(lines[j] || "");
          if (!t.trim()) break;
          if (isNumberOnly(t)) break;
          chunk.push(t.trim());
          j += 1;
        }

        if (!chunk.length) {
          out.push(`${num}.`);
          i = j - 1;
          continue;
        }

        const title = chunk[0];
        out.push(`${num}. ${title}`);
        for (const bodyLine of chunk.slice(1)) {
          out.push(`   ${bodyLine}`);
        }

        out.push("");
        i = j - 1;
      }

      const normalized = out
        .join("\n")
        .replace(/\n{3,}/g, "\n\n")
        .replace(/\n\s*\n\s*\n/g, "\n\n");

      const normalized2 = normalized
        .split("\n")
        .map((ln) => {
          const t = String(ln || "").trim();
          if (!t) return ln;
          const up = t.toUpperCase();
          if (up === "КОММЕРЧЕСКАЯ ТАЙНА" || up === "КОММЕРЧЕСКАЯ ТАЙНА." || up === "КОММЕРЧЕСКАЯ ТАЙНА:" || up === "КОММЕРЧЕСКАЯ ТАЙНА!") {
            return `> **${t.replace(/[:.!]+$/g, "")}**`;
          }
          if (/^КОММЕРЧ(Е|Ё)СК/i.test(t) && /ТАЙН/i.test(t)) {
            return `> **${t}**`;
          }
          return ln;
        })
        .join("\n");

      return normalized2
        .replace(/\n{3,}/g, "\n\n")
        .trim();
    } catch {
      return String(submodule?.content || "");
    }
  }, [submodule]);

  const stripMarkdownForSpeech = (input: string): string => {
    try {
      let s = String(input || "");
      s = s.replace(/```[\s\S]*?```/g, " ");
      s = s.replace(/`([^`]+)`/g, "$1");
      s = s.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, "$1");
      s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1");
      s = s.replace(/^\s{0,3}#{1,6}\s+/gm, "");
      s = s.replace(/\*\*([^*]+)\*\*/g, "$1");
      s = s.replace(/__([^_]+)__/g, "$1");
      s = s.replace(/\*([^*]+)\*/g, "$1");
      s = s.replace(/_([^_]+)_/g, "$1");
      s = s.replace(/^\s*>\s?/gm, "");
      s = s.replace(/^\s*[-*+]\s+/gm, "");
      s = s.replace(/^\s*\d+\.?\)\s+/gm, "");
      s = s.replace(/\|/g, " ");
      return s;
    } catch {
      return String(input || "");
    }
  };

  const getSpeakText = (): string => {
    try {
      const raw = normalizeTheoryText(stripMarkdownForSpeech(String(submodule?.content || "")));
      const t = raw
        .replace(/\s+\n/g, "\n")
        .replace(/\n{3,}/g, "\n\n")
        .replace(/\s{2,}/g, " ")
        .trim();
      return t.length > 12000 ? t.slice(0, 12000) + "…" : t;
    } catch {
      return "";
    }
  };

  useEffect(() => {
    if (typeof window === "undefined") return;
    const synth = (window as any).speechSynthesis as SpeechSynthesis | undefined;
    if (!synth) return;

    const readVoices = () => {
      try {
        const voices = synth.getVoices() || [];
        const mapped = voices
          .map((v) => ({ voiceURI: String(v.voiceURI || ""), name: String(v.name || ""), lang: String(v.lang || "") }))
          .filter((v) => v.voiceURI);

        const allow = ["microsoft dmitry", "microsoft svetlana"];
        const onlyTwo = mapped.filter((v) => allow.some((a) => v.name.toLowerCase().includes(a)));
        const finalList = onlyTwo.length ? onlyTwo : mapped;
        setAvailableVoices(finalList);

        if (!speakVoiceUri && finalList.length) {
          const preferred =
            finalList.find((v) => v.name.toLowerCase().includes("microsoft dmitry")) ||
            finalList.find((v) => v.name.toLowerCase().includes("microsoft svetlana")) ||
            finalList.find((v) => v.lang.toLowerCase().startsWith("ru")) ||
            finalList[0] ||
            { voiceURI: "" };
          setSpeakVoiceUri(preferred.voiceURI);
        }
      } catch {
        // ignore
      }
    };

    readVoices();
    try {
      (synth as any).addEventListener?.("voiceschanged", readVoices);
    } catch {
      // ignore
    }
    return () => {
      try {
        (synth as any).removeEventListener?.("voiceschanged", readVoices);
      } catch {
        // ignore
      }
    };
  }, [speakVoiceUri]);

  const stopSpeaking = () => {
    try {
      speakActiveRef.current = false;
      setIsSpeakPaused(false);
      if (typeof window !== "undefined" && (window as any).speechSynthesis) {
        window.speechSynthesis.cancel();
      }
    } catch {
      // ignore
    } finally {
      setIsSpeaking(false);
    }
  };

  const pauseSpeaking = () => {
    try {
      if (typeof window === "undefined") return;
      const synth = (window as any).speechSynthesis as SpeechSynthesis | undefined;
      if (!synth) return;
      if (!speakActiveRef.current) return;
      synth.pause();
      setIsSpeakPaused(true);
    } catch {
      // ignore
    }
  };

  const resumeSpeaking = () => {
    try {
      if (typeof window === "undefined") return;
      const synth = (window as any).speechSynthesis as SpeechSynthesis | undefined;
      if (!synth) return;
      if (!speakActiveRef.current) return;
      synth.resume();
      setIsSpeakPaused(false);
    } catch {
      // ignore
    }
  };

  const startSpeaking = () => {
    try {
      if (typeof window === "undefined") return;
      const synth = (window as any).speechSynthesis as SpeechSynthesis | undefined;
      if (!synth) return;

      const text = getSpeakText();
      if (!text) return;

      synth.cancel();
      speakActiveRef.current = true;
      setIsSpeaking(true);
      setIsSpeakPaused(false);

      const pickVoice = (): SpeechSynthesisVoice | null => {
        try {
          const voices = synth.getVoices() || [];
          const wantedUri = String(speakVoiceUri || "").trim();
          if (wantedUri) {
            const exact = voices.find((v) => String(v.voiceURI || "").trim() === wantedUri);
            if (exact) return exact;
          }
          const allow = ["microsoft dmitry", "microsoft svetlana"];
          const preferred = voices.find((v) => allow.some((a) => String(v.name || "").toLowerCase().includes(a)));
          if (preferred) return preferred;
          const ru = voices.filter((v) => String(v.lang || "").toLowerCase().startsWith("ru"));
          return (ru[0] || voices[0] || null) as any;
        } catch {
          return null;
        }
      };

      const voice = pickVoice();
      const parts = text
        .split(/(?<=[.!?])\s+/)
        .map((x) => String(x || "").trim())
        .filter(Boolean);

      const queue: string[] = [];
      let buf = "";
      for (const p of parts) {
        if (!buf) {
          buf = p;
          continue;
        }
        if ((buf + " " + p).length <= 380) {
          buf = buf + " " + p;
        } else {
          queue.push(buf);
          buf = p;
        }
      }
      if (buf) queue.push(buf);

      let idx = 0;
      const speakNext = () => {
        if (!speakActiveRef.current) return;
        if (idx >= queue.length) {
          speakActiveRef.current = false;
          setIsSpeaking(false);
          return;
        }
        const u = new SpeechSynthesisUtterance(queue[idx]);
        if (voice) u.voice = voice;
        u.rate = Math.max(0.7, Math.min(1.3, Number(speakRate || 1)));
        u.pitch = Math.max(0.7, Math.min(1.3, Number(speakPitch || 1)));
        u.onend = () => {
          idx += 1;
          speakNext();
        };
        u.onerror = () => {
          speakActiveRef.current = false;
          setIsSpeakPaused(false);
          setIsSpeaking(false);
        };
        try {
          synth.speak(u);
        } catch {
          speakActiveRef.current = false;
          setIsSpeakPaused(false);
          setIsSpeaking(false);
        }
      };

      // Some browsers populate voices asynchronously.
      try {
        if (!synth.getVoices().length) {
          const onVoices = () => {
            try {
              (synth as any).removeEventListener?.("voiceschanged", onVoices);
            } catch {
              // ignore
            }
            speakNext();
          };
          (synth as any).addEventListener?.("voiceschanged", onVoices);
          window.setTimeout(() => speakNext(), 150);
          return;
        }
      } catch {
        // ignore
      }
      speakNext();
    } catch {
      stopSpeaking();
    }
  };

  useEffect(() => {
    return () => {
      stopSpeaking();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function closeInline() {
    setInlineUrl(null);
    setInlineMime(null);
    setInlineName(null);
    setInlineText(null);
    setInlineAssetId(null);
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

  const lessonContentBlocks = useMemo<InlineTextBlock[]>(() => {
    const raw = String(submodule?.content || "").replace(/\r\n/g, "\n").trim();
    if (!raw) return [];

    const shortened = raw.length > 30000 ? raw.slice(0, 30000) + "\n\n…" : raw;
    const lines = shortened.split("\n");
    const blocks: InlineTextBlock[] = [];
    let paragraph: string[] = [];
    let list: string[] = [];

    const isNumberOnlyLine = (ln: string) => /^\d{1,3}\.$/.test(ln.trim());
    const isListLine = (ln: string) =>
      /^(-|•|\*)\s+/.test(ln) ||
      /^\d{1,3}\.\s+/.test(ln) ||
      /^\d{1,3}[.)]\s+/.test(ln) ||
      /^\d{1,3}\s*[-—]\s+/.test(ln);

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

    const nextNonEmpty = (start: number) => {
      for (let i = start; i < lines.length; i++) {
        const t = String(lines[i] || "").trim();
        if (t) return t;
      }
      return "";
    };

    for (let i = 0; i < lines.length; i++) {
      const ln = String(lines[i] || "").trim();
      if (!ln) {
        flushList();
        flushParagraph();
        continue;
      }

      if (isNumberOnlyLine(ln)) {
        flushParagraph();
        let j = i + 1;
        while (j < lines.length && !String(lines[j] || "").trim()) j += 1;

        if (j >= lines.length) {
          flushList();
          paragraph.push(ln);
          continue;
        }

        const parts: string[] = [];
        while (j < lines.length) {
          const t = String(lines[j] || "").trim();
          if (!t) break;
          if (isNumberOnlyLine(t) || isListLine(t)) break;
          parts.push(t);
          j += 1;
        }

        if (!parts.length) {
          flushList();
          paragraph.push(ln);
          continue;
        }

        list.push(parts.join(" ").replace(/\s+/g, " ").trim());
        i = j - 1;
        continue;
      }

      const headerByColon = /^(.*?):\s*$/.exec(ln);
      const looksLikeHeader =
        Boolean(headerByColon) ||
        (!isListLine(ln) && !/[.!?]$/.test(ln) && isListLine(nextNonEmpty(i + 1)) && ln.length <= 120);
      if (looksLikeHeader) {
        flushList();
        flushParagraph();
        const title = (headerByColon ? String(headerByColon[1] || "").trim() : ln).replace(/\s+/g, " ").trim();
        if (title) blocks.push({ kind: "h", text: title });
        continue;
      }

      if (isListLine(ln)) {
        flushParagraph();
        list.push(
          ln
            .replace(/^(-|•|\*)\s+/, "")
            .replace(/^\d{1,3}[.)]\s+/, "")
            .replace(/^\d{1,3}\s*[-—]\s+/, "")
            .trim()
        );
        continue;
      }

      flushList();
      paragraph.push(ln);
    }

    flushList();
    flushParagraph();
    if (!blocks.length) return [{ kind: "pre", text: shortened }];
    return blocks;
  }, [submodule?.content]);

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

        const subs = await apiFetch<ModuleSubmoduleListItem[]>(`/modules/${effectiveModuleId}/submodules`);
        setModuleSubmodules(Array.isArray(subs) ? subs : []);
      } else {
        setModuleAssets([]);
        setModuleSubmodules([]);
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

  function streamUrl(assetId: string): string {
    return `/api/backend/assets/${encodeURIComponent(String(assetId || "").trim())}/stream`;
  }

  async function presignViewUrl(assetId: string): Promise<string> {
    const sid = String(assetId || "").trim();
    const r = await apiFetch<{ asset_id: string; download_url: string }>(
      `/assets/${encodeURIComponent(sid)}/presign-download?action=view`,
      { method: "GET" }
    );
    const u = String((r as any)?.download_url || "").trim();
    if (!u) throw new Error("missing presigned url");
    return u;
  }

  async function onOpenInline(a: AssetLike) {
    try {
      const stream = streamUrl(a.asset_id);
      setInlineMime(a.mime_type || null);
      const anyA = a as any;
      const nm = String(anyA?.original_filename || anyA?.name || "").trim();
      setInlineName(nm || null);
      setInlineAssetId(String(a.asset_id || "").trim() || null);

      const mime = String(a.mime_type || "").toLowerCase();
      const ext = getExtFromName(nm);

      const isOffice = ["doc", "docx", "ppt", "pptx", "xls", "xlsx"].includes(ext);
      const isTextLike = ["csv", "json"].includes(ext);

      const kind: InlineKind =
        mime.includes("pdf") || ext === "pdf"
          ? "pdf"
          : mime.startsWith("audio/") || ["mp3", "wav", "ogg", "m4a"].includes(ext)
            ? "audio"
            : mime.startsWith("video/") || ["mp4", "webm", "mov", "mkv"].includes(ext)
          ? "video"
          : mime.startsWith("image/") || ["png", "jpg", "jpeg", "webp", "gif", "svg"].includes(ext)
            ? "image"
              : mime.startsWith("text/") || ["txt", "md"].includes(ext) || isTextLike
                ? "text"
              : isOffice
                ? "office"
                : "iframe";
      setInlineKind(kind);

      const chosenUrl =
        kind === "office" || kind === "video" || kind === "audio" || kind === "pdf" || kind === "image"
          ? await presignViewUrl(a.asset_id)
          : stream;

      if (kind === "office") {
        try {
          const officeUrl = `https://view.officeapps.live.com/op/embed.aspx?src=${encodeURIComponent(chosenUrl)}`;
          setInlineUrl(officeUrl);
        } catch {
          setInlineUrl(chosenUrl);
        }
      } else {
        if (chosenUrl) setInlineUrl(chosenUrl);
      }

      if (kind === "text") {
        try {
          const targetUrl = String(chosenUrl || "").trim();
          const resp = await fetch(targetUrl || stream, {
            method: "GET",
            credentials: "include",
          });
          if (!resp.ok) {
            if (resp.status === 404) {
              throw new Error("Файл удалён из хранилища (404). Переимпортируйте модуль или загрузите файл заново.");
            }
            throw new Error(`Не удалось загрузить текст (код ${resp.status}).`);
          }
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

  const assetBrowser = useMemo(() => {
    const sep = "/";
    const safeSeg = (s: string) => String(s || "").replaceAll("\\", "/").split("/").filter(Boolean);
    const entries: Array<
      | { type: "dir"; name: string; path: string[] }
      | { type: "file"; name: string; path: string[]; asset: SubmoduleAsset }
    > = [];

    const dirs = new Map<string, Set<string>>();
    const files: Array<{ full: string[]; asset: SubmoduleAsset }> = [];

    for (const a of lessonMaterials) {
      const raw = String((a as any)?.original_filename || "").trim();
      if (!raw) continue;
      const full = safeSeg(raw);
      if (!full.length) continue;
      files.push({ full, asset: a });
    }

    const cur = (assetNavPath || []).filter((x): x is string => Boolean(x));
    const curKey = cur.join(sep);

    for (const f of files) {
      const parent = f.full.slice(0, -1);
      const fileName = f.full[f.full.length - 1];
      const parentKey = parent.join(sep);
      if (!dirs.has(parentKey)) dirs.set(parentKey, new Set<string>());
      for (let i = 0; i < parent.length; i++) {
        const pk = parent.slice(0, i).join(sep);
        const child = parent[i];
        if (!dirs.has(pk)) dirs.set(pk, new Set<string>());
        dirs.get(pk)!.add(child);
      }
      if (!dirs.has("")) dirs.set("", new Set<string>());
      if (parent.length >= 1) dirs.get("")!.add(parent[0]);

      if (parentKey === curKey) {
        entries.push({ type: "file", name: fileName, path: f.full, asset: f.asset });
      }
    }

    const childDirs: string[] = [...(dirs.get(curKey) ?? new Set<string>())];
    for (const d of childDirs) {
      entries.push({ type: "dir", name: d, path: cur.concat([d]) });
    }

    entries.sort((a, b) => {
      if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
      return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
    });

    return {
      current: cur,
      entries,
      hasAny: lessonMaterials.length > 0,
    };
  }, [assetNavPath, lessonMaterials]);

  const primaryLessonAsset = useMemo<SubmoduleAsset | null>(() => {
    return lessonMaterials.length ? lessonMaterials[0] : null;
  }, [lessonMaterials]);

  useEffect(() => {
    setInlineUrl(null);
    setInlineMime(null);
    setInlineName(null);
    setInlineText(null);
    setInlineAssetId(null);
    setInlineKind("iframe");
    setAssetNavPath([]);
  }, [submoduleId]);

  useEffect(() => {
    if (!isFileLesson) return;
    if (!primaryLessonAsset) return;
    if (inlineUrl) return;
    void onOpenInline(primaryLessonAsset);
  }, [isFileLesson, primaryLessonAsset, inlineUrl]);

  const noQuizLessonMaterials = useMemo(() => {
    const sid = String(submoduleId || "").trim();
    const items = (moduleSubmodules || [])
      .filter((s) => !s?.requires_quiz)
      .filter((s) => String(s?.id || "").trim() && String(s.id).trim() !== sid)
      .slice();
    items.sort((a, b) => Number(a.order || 0) - Number(b.order || 0));
    return items;
  }, [moduleSubmodules, submoduleId]);

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
    const raw = normalizeTheoryText(String(submodule?.content || "")).replace(/\r\n/g, "\n").trim();
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

      // Immediately refresh module progress so UI updates without waiting for navigation.
      try {
        if (moduleId) {
          const prog = await apiFetch<any>(`/progress/modules/${moduleId}`);
          setModuleProgress(prog);
        }
      } catch {
        // ignore
      }

      const xp = Number(resp?.xp_awarded || 0);
      if (xp > 0 && typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("corelms:toast", {
          detail: { title: `+${xp} XP`, description: "Теория изучена" },
        }));
      }
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("corelms:refresh-me", { detail: { reason: "progress" } }));
        try {
          localStorage.setItem("corelms:modules-updated", String(Date.now()));
        } catch {
          // ignore
        }
        window.dispatchEvent(new Event("corelms:modules-updated"));
      }
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
        <div className="grid gap-10 lg:grid-cols-12 items-start">
          <div className="lg:col-span-8">
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

            <div className="mt-6">
              <Link href={`/modules/${moduleId}`}>
                <Button variant="ghost" size="sm" className="rounded-xl font-black uppercase tracking-widest text-[10px]">
                  <ChevronLeft className="mr-2 h-4 w-4" />
                  оглавление
                </Button>
              </Link>
            </div>
          </div>

          <div className="lg:col-span-4" />
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

                {isFileLesson && inlineUrl ? (
                  <div ref={inlineRef} className="mb-10 overflow-hidden rounded-[24px] border border-zinc-200 bg-white shadow-sm">
                    {canInlinePreview ? (
                      <div className="overflow-hidden rounded-2xl bg-white">
                        {["pdf"].includes(String(inlineKind || "")) ? (
                          <div className="flex items-center justify-end gap-2 border-b border-zinc-200 bg-white p-4">
                            <Button
                              variant="outline"
                              className="h-9 rounded-xl font-black uppercase tracking-widest text-[9px]"
                              onClick={() => window.open(inlineUrl, "_blank", "noopener,noreferrer")}
                            >
                              ОТКРЫТЬ В НОВОЙ ВКЛАДКЕ
                            </Button>
                          </div>
                        ) : null}
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
                                {inlineTextBlocks.map((b: InlineTextBlock, idx: number) =>
                                  b.kind === "h" ? (
                                    <div key={idx} className="text-sm font-black uppercase tracking-widest text-zinc-900">
                                      {b.text}
                                    </div>
                                  ) : b.kind === "ul" ? (
                                    <ul key={idx} className="list-disc pl-5 text-sm text-zinc-800 font-medium space-y-1">
                                      {(b.items || []).map((it: string, j: number) => (
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
                          Этот формат не поддерживает предпросмотр в браузере.
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : null}


                
                <div className="max-w-none break-words hyphens-auto text-zinc-700 text-[17px] leading-relaxed">
                  {isFileLesson ? null : (
                    <div className="not-prose mb-6 rounded-2xl border border-zinc-200 bg-white p-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          variant={isSpeaking ? "secondary" : "outline"}
                          className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
                          onClick={() => (isSpeaking ? stopSpeaking() : startSpeaking())}
                          disabled={!String(submodule?.content || "").trim()}
                        >
                          {isSpeaking ? "СТОП" : "СЛУШАТЬ"}
                        </Button>
                        <Button
                          variant="outline"
                          className="h-10 rounded-xl font-black uppercase tracking-widest text-[9px]"
                          onClick={() => (isSpeakPaused ? resumeSpeaking() : pauseSpeaking())}
                          disabled={!isSpeaking}
                        >
                          {isSpeakPaused ? "ПРОДОЛЖИТЬ" : "ПАУЗА"}
                        </Button>

                        {(() => {
                          const male = availableVoices.find((v: { voiceURI: string; name: string; lang: string }) =>
                            v.name.toLowerCase().includes("microsoft dmitry"),
                          );
                          const female = availableVoices.find((v: { voiceURI: string; name: string; lang: string }) =>
                            v.name.toLowerCase().includes("microsoft svetlana"),
                          );
                          const hasTwo = Boolean(male?.voiceURI) && Boolean(female?.voiceURI);

                          if (hasTwo) {
                            return (
                              <div className="ml-auto flex flex-wrap items-center gap-2">
                                <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Голос</div>
                                <div className="flex items-center gap-2">
                                  <label className="flex items-center gap-2 rounded-xl border border-zinc-200 bg-white px-3 py-2">
                                    <input
                                      type="radio"
                                      name="tts-voice"
                                      value={male!.voiceURI}
                                      checked={speakVoiceUri === male!.voiceURI}
                                      onChange={(e: ChangeEvent<HTMLInputElement>) => setSpeakVoiceUri(String(e.target.value || ""))}
                                    />
                                    <div className="text-xs font-black text-zinc-900">Мужской</div>
                                  </label>
                                  <label className="flex items-center gap-2 rounded-xl border border-zinc-200 bg-white px-3 py-2">
                                    <input
                                      type="radio"
                                      name="tts-voice"
                                      value={female!.voiceURI}
                                      checked={speakVoiceUri === female!.voiceURI}
                                      onChange={(e: ChangeEvent<HTMLInputElement>) => setSpeakVoiceUri(String(e.target.value || ""))}
                                    />
                                    <div className="text-xs font-black text-zinc-900">Женский</div>
                                  </label>
                                </div>
                                <div className="ml-3 text-[9px] font-black uppercase tracking-widest text-zinc-500">
                                  {isSpeaking ? (isSpeakPaused ? "Озвучка (пауза)" : "Озвучка") : "Озвучить урок"}
                                </div>
                              </div>
                            );
                          }

                          return (
                            <div className="ml-auto flex flex-wrap items-center gap-2">
                              <div className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Голос</div>
                              <select
                                className="h-10 w-[220px] max-w-full rounded-xl border border-zinc-200 bg-white px-3 text-xs font-bold text-zinc-900"
                                value={speakVoiceUri}
                                onChange={(e: ChangeEvent<HTMLSelectElement>) => setSpeakVoiceUri(String(e.target.value || ""))}
                                disabled={!availableVoices.length}
                              >
                                {(availableVoices.length ? availableVoices : [{ voiceURI: "", name: "Системный", lang: "" }]).map(
                                  (v: { voiceURI: string; name: string; lang: string }) => (
                                    <option key={v.voiceURI || "sys"} value={v.voiceURI}>
                                      {v.name}
                                      {v.lang ? ` (${v.lang})` : ""}
                                    </option>
                                  ),
                                )}
                              </select>
                              <div className="ml-3 text-[9px] font-black uppercase tracking-widest text-zinc-500">
                                {isSpeaking ? (isSpeakPaused ? "Озвучка (пауза)" : "Озвучка") : "Озвучить урок"}
                              </div>
                            </div>
                          );
                        })()}
                      </div>

                      <div className="mt-3 grid gap-3 md:grid-cols-2">
                        <div>
                          <div className="flex items-center justify-between text-[9px] font-black uppercase tracking-widest text-zinc-500">
                            <span>Скорость</span>
                            <span className="text-zinc-700">{Number(speakRate || 1).toFixed(2)}</span>
                          </div>
                          <input
                            type="range"
                            min={0.7}
                            max={1.3}
                            step={0.01}
                            value={speakRate}
                            onChange={(e: ChangeEvent<HTMLInputElement>) => setSpeakRate(Number(e.target.value))}
                            className="mt-2 w-full"
                          />
                        </div>

                        <div>
                          <div className="flex items-center justify-between text-[9px] font-black uppercase tracking-widest text-zinc-500">
                            <span>Тон</span>
                            <span className="text-zinc-700">{Number(speakPitch || 1).toFixed(2)}</span>
                          </div>
                          <input
                            type="range"
                            min={0.7}
                            max={1.3}
                            step={0.01}
                            value={speakPitch}
                            onChange={(e: ChangeEvent<HTMLInputElement>) => setSpeakPitch(Number(e.target.value))}
                            className="mt-2 w-full"
                          />
                        </div>
                      </div>
                    </div>
                  )}
                  {isFileLesson ? null : (
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      className="max-w-[860px] text-[15px] leading-7 text-zinc-900"
                      components={{
                        h1: ({ children }: { children?: ReactNode }) => (
                          <h1 className="mt-8 mb-3 text-2xl font-black tracking-tight text-zinc-950">{children}</h1>
                        ),
                        h2: ({ children }: { children?: ReactNode }) => (
                          <h2 className="mt-7 mb-3 text-xl font-black tracking-tight text-zinc-950">{children}</h2>
                        ),
                        h3: ({ children }: { children?: ReactNode }) => (
                          <h3 className="mt-6 mb-2 text-lg font-black tracking-tight text-zinc-950">{children}</h3>
                        ),
                        p: ({ children }: { children?: ReactNode }) => (
                          <p className="my-4 whitespace-pre-line break-words leading-7 text-zinc-900">{children}</p>
                        ),
                        ul: ({ children }: { children?: ReactNode }) => <ul className="my-3 list-disc pl-6 space-y-2">{children}</ul>,
                        ol: ({ children }: { children?: ReactNode }) => <ol className="my-5 list-decimal pl-8 space-y-3">{children}</ol>,
                        li: ({ children }: { children?: ReactNode }) => (
                          <li className="pl-1 whitespace-pre-line break-words leading-7 marker:font-black marker:text-zinc-400">{children}</li>
                        ),
                        a: ({ children, href }: { children?: ReactNode; href?: string }) => (
                          <a className="text-[#fe9900] font-bold underline underline-offset-4" href={href} target="_blank" rel="noopener noreferrer">
                            {children}
                          </a>
                        ),
                        code: ({ children }: { children?: ReactNode }) => (
                          <code className="rounded-md bg-zinc-100 px-1.5 py-0.5 font-mono text-[0.92em] text-zinc-900">{children}</code>
                        ),
                        pre: ({ children }: { children?: ReactNode }) => (
                          <pre className="my-4 overflow-auto rounded-2xl border border-zinc-200 bg-zinc-50 p-4 text-xs leading-relaxed text-zinc-900">{children}</pre>
                        ),
                        hr: () => <hr className="my-6 border-zinc-200" />,
                        blockquote: ({ children }: { children?: ReactNode }) => (
                          <blockquote className="my-6 rounded-2xl border border-[#fe9900]/25 bg-[#fe9900]/10 p-5 text-zinc-950">{children}</blockquote>
                        ),
                      }}
                    >
                      {lessonMarkdownForDisplay.trim() || "Загрузка контента..."}
                    </ReactMarkdown>
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
