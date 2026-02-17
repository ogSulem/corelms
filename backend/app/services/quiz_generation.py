from __future__ import annotations

import random
import re
from dataclasses import dataclass


def _clean_line(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_facts(text: str) -> list[str]:
    if not text:
        return []

    lines = [_clean_line(x) for x in re.split(r"\r?\n", text) if _clean_line(x)]

    picked: list[str] = []
    for ln in lines:
        if re.match(r"^(\d{1,2}|[\-•])\s*[.)\-]?\s+", ln):
            picked.append(re.sub(r"^(\d{1,2}|[\-•])\s*[.)\-]?\s+", "", ln).strip())

    if len(picked) < 6:
        for ln in lines:
            if 25 <= len(ln) <= 170:
                picked.append(ln)

    uniq: list[str] = []
    seen: set[str] = set()
    for x in picked:
        x = _clean_line(x)
        if not x:
            continue
        key = x.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(x)

    # If content is short or badly formatted, fall back to sentence splitting.
    if len(uniq) < 8:
        try:
            sents = [
                _clean_line(s)
                for s in re.split(r"[.!?]+\s+", (text or "").strip())
                if _clean_line(s)
            ]
        except Exception:
            sents = []
        for s in sents:
            if 25 <= len(s) <= 170:
                key = s.lower()
                if key not in seen:
                    seen.add(key)
                    uniq.append(s)

    return uniq[:40]


def _pad_facts(*, title: str, facts: list[str]) -> list[str]:
    # Deterministic, human-readable padding so question generation always works.
    base = list(facts or [])
    if len(base) >= 10:
        return base

    t = _clean_line(title) or "уроку"
    seeds = [
        f"Урок «{t}»: ключевой шаг — корректно оформить документы.",
        f"Урок «{t}»: важно соблюдать порядок действий.",
        f"Урок «{t}»: проверь данные перед отправкой.",
        f"Урок «{t}»: следуй регламенту компании.",
        f"Урок «{t}»: фиксируй результат в системе.",
        f"Урок «{t}»: обрати внимание на сроки и статусы.",
        f"Урок «{t}»: используйте утверждённые шаблоны.",
        f"Урок «{t}»: согласование — обязательный этап.",
        f"Урок «{t}»: типичная ошибка — пропуск проверки.",
        f"Урок «{t}»: финальный контроль качества обязателен.",
    ]
    for s in seeds:
        if len(base) >= 10:
            break
        ss = _clean_line(s)
        if ss and ss.lower() not in {x.lower() for x in base}:
            base.append(ss)
    return base


@dataclass(frozen=True)
class MCQ:
    prompt: str
    correct_answer: str
    qtype: str  # single|multi


def _format_mcq_prompt(*, stem: str, options: list[str]) -> str:
    letters = ["A", "B", "C", "D"]
    out = [stem.strip()]
    for i, opt in enumerate(options[:4]):
        out.append(f"{letters[i]}) {opt}")
    return "\n".join(out)


def make_single(*, title: str, facts: list[str], rng: random.Random) -> MCQ | None:
    if len(facts) < 4:
        return None
    correct = rng.choice(facts)
    distractors = [x for x in facts if x != correct]
    rng.shuffle(distractors)
    opts = [correct] + distractors[:3]
    rng.shuffle(opts)
    correct_letter = ["A", "B", "C", "D"][opts.index(correct)]
    stem = f"Что из перечисленного относится к уроку «{title}»?"
    return MCQ(prompt=_format_mcq_prompt(stem=stem, options=opts), correct_answer=correct_letter, qtype="single")


def make_multi(*, title: str, facts: list[str], rng: random.Random) -> MCQ | None:
    if len(facts) < 6:
        return None

    pool = list(facts)
    rng.shuffle(pool)
    correct_set = pool[:2]
    distractors = pool[2:]
    opts = correct_set + distractors[:2]
    rng.shuffle(opts)

    letters = ["A", "B", "C", "D"]
    correct_letters = [letters[i] for i, o in enumerate(opts) if o in correct_set]
    correct_answer = ",".join(sorted(correct_letters))
    stem = f"Выберите верные утверждения по уроку «{title}» (ответ буквами, пример: A,C)."
    return MCQ(prompt=_format_mcq_prompt(stem=stem, options=opts), correct_answer=correct_answer, qtype="multi")


def generate_quiz_questions_heuristic(*, seed: str, title: str, theory_text: str, target: int = 3) -> list[MCQ]:
    facts = _pad_facts(title=title, facts=extract_facts(theory_text))
    rng = random.Random(seed)

    out: list[MCQ] = []
    want = max(1, int(target or 1))
    # Generate a mix of single/multi questions up to `target`.
    while len(out) < want:
        if len(out) % 3 == 2:
            q = make_multi(title=title, facts=facts, rng=rng)
        else:
            q = make_single(title=title, facts=facts, rng=rng)
        if q:
            out.append(q)
        else:
            # Should be rare with padded facts, but keep a safe deterministic fallback.
            stem = f"По уроку «{title}» выберите верный вариант."
            opts = [
                "Следовать регламенту",
                "Игнорировать порядок действий",
                "Пропустить проверку данных",
                "Не фиксировать результат",
            ]
            rng.shuffle(opts)
            prompt = _format_mcq_prompt(stem=stem, options=opts)
            out.append(MCQ(prompt=prompt, correct_answer=["A", "B", "C", "D"][opts.index("Следовать регламенту")], qtype="single"))

    return out[:want]
