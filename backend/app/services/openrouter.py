from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.redis_client import get_redis


log = logging.getLogger(__name__)


class OpenRouterQuestion(BaseModel):
    type: str
    prompt: str
    correct_answer: str
    explanation: str | None = None


class OpenRouterQuizResponse(BaseModel):
    questions: list[OpenRouterQuestion]


def _extract_abcd_options(prompt: str) -> list[str] | None:
    # Expect 4 options formatted like A) / A. / A: / A - / A —.
    # We keep it fairly strict but tolerate common separators.
    if not prompt:
        return None
    lines = [ln.strip() for ln in str(prompt).splitlines() if ln.strip()]
    opts: dict[str, str] = {}
    for ln in lines:
        if len(ln) < 3:
            continue
        head2 = ln[:2].upper()
        head3 = ln[:3].upper() if len(ln) >= 3 else head2
        key = ""
        val = ""
        if head2 in {"A)", "B)", "C)", "D)"}:
            key = head2[0]
            val = ln[2:].strip()
        elif head2 and head2[0] in {"A", "B", "C", "D"} and head2[1] in {".", ":"}:
            key = head2[0]
            val = ln[2:].strip()
        elif head3 and head3[0] in {"A", "B", "C", "D"} and head3[1] == " " and head3[2] in {"-", "—"}:
            key = head3[0]
            val = ln[3:].strip()
        else:
            continue

        if key and val:
            opts[key] = val
    if all(k in opts for k in ("A", "B", "C", "D")):
        return [opts["A"], opts["B"], opts["C"], opts["D"]]
    return None


def _is_good_question(q: OpenRouterQuestion, *, seen_prompts: set[str]) -> bool:
    prompt = str(q.prompt or "").strip()
    if not prompt or len(prompt) < 18:
        return False

    # Avoid duplicates inside a single response.
    norm_p = re.sub(r"\s+", " ", prompt).strip().lower()
    if norm_p in seen_prompts:
        return False

    # Must have 4 options and they must be distinct and non-trivial.
    opts = _extract_abcd_options(prompt)
    if not opts:
        return False
    norm_opts = [re.sub(r"\s+", " ", str(o)).strip().lower() for o in opts]
    if len({o for o in norm_opts if o}) != 4:
        return False
    if any(len(o) < 2 for o in norm_opts):
        return False

    ca = str(q.correct_answer or "").strip().upper()[:1]
    if ca not in {"A", "B", "C", "D"}:
        return False

    # Explanation is required for quality.
    exp = str(q.explanation or "").strip()
    if len(exp) < 6:
        return False

    seen_prompts.add(norm_p)
    return True


def _format_options_for_prompt(options: object) -> str:
    if not isinstance(options, list):
        return ""
    items = [str(x or "").strip() for x in options if str(x or "").strip()]
    if not items:
        return ""

    has_labels = any(it.startswith("A)") or it.startswith("B)") or it.startswith("C)") or it.startswith("D)") for it in items)
    if has_labels:
        return "\n" + "\n".join(items)

    letters = ["A", "B", "C", "D"]
    labeled: list[str] = []
    for i, it in enumerate(items[:4]):
        labeled.append(f"{letters[i]}) {it}")
    return "\n" + "\n".join(labeled)


def _correct_letter_from_index(idx: object) -> str:
    try:
        i = int(idx)
    except Exception:
        if bool(getattr(settings, "llm_debug_log", False)) or bool(getattr(settings, "llm_debug_save", False)):
            log.debug("openrouter: invalid correct_index", exc_info=True)
        return ""
    if i == 0:
        return "A"
    if i == 1:
        return "B"
    if i == 2:
        return "C"
    if i == 3:
        return "D"
    return ""


def _pick_correct_answer(
    *,
    correct_raw: object,
    correct_index: object,
    options: object,
) -> str:
    # 1) explicit correct_index -> letter
    letter = _correct_letter_from_index(correct_index)
    if letter:
        return letter

    # 2) correct_answer variants -> first letter
    s = str(correct_raw or "").strip()
    if s:
        first = s[:1].upper()
        if first in {"A", "B", "C", "D"}:
            return first

    # 3) if correct_raw equals one of options texts, map to index
    if isinstance(options, list) and s:
        norm = s.strip().lower()
        for i, opt in enumerate(options[:4]):
            o = str(opt or "").strip()
            if not o:
                continue
            o_norm = o.strip().lower()
            # tolerate already-labeled options
            for prefix in ("a)", "b)", "c)", "d)"):
                if o_norm.startswith(prefix):
                    o_norm = o_norm[len(prefix) :].strip()
            if norm == o_norm:
                return _correct_letter_from_index(i)

    return ""


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None

    s = str(text).strip()
    if not s:
        return None

    dbg = bool(getattr(settings, "llm_debug_log", False)) or bool(getattr(settings, "llm_debug_save", False))

    # Strip common Markdown wrappers.
    try:
        s = re.sub(r"^```(?:json)?\s*", "", s.strip(), flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s.strip())
    except Exception:
        if dbg:
            log.debug("openrouter: failed to strip markdown wrappers", exc_info=True)

    # Fast path: parse if the whole payload is a JSON object/array.
    try:
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            obj_any = json.loads(s)
            if isinstance(obj_any, dict):
                return obj_any
            if isinstance(obj_any, list):
                return {"questions": obj_any}
    except Exception:
        if dbg:
            log.debug("openrouter: json fast-parse failed", exc_info=True)

    # Robust path: find the first JSON object/array inside arbitrary text.
    dec = json.JSONDecoder()
    for start_ch in ("{", "["):
        try:
            i = s.find(start_ch)
            if i < 0:
                continue
            obj_any, _end = dec.raw_decode(s[i:])
            if isinstance(obj_any, dict):
                return obj_any
            if isinstance(obj_any, list):
                return {"questions": obj_any}
        except Exception:
            if dbg:
                log.debug("openrouter: json raw_decode failed", exc_info=True)

    # Last resort: greedy brace capture.
    try:
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            obj_any = json.loads(m.group(0))
            if isinstance(obj_any, dict):
                return obj_any
    except Exception:
        if dbg:
            log.debug("openrouter: greedy json parse failed", exc_info=True)

    return None


def generate_quiz_questions_openrouter(
    *,
    title: str,
    text: str,
    n_questions: int = 3,
    debug_out: dict[str, Any] | None = None,
    base_url: str | None = None,
    model: str | None = None,
    system_prompt: str | None = None,
    temperature: float | None = None,
    timeout_read_seconds: float | None = None,
    repair_text: str | None = None,
) -> list[OpenRouterQuestion]:
    if debug_out is not None:
        debug_out.setdefault("provider", "openrouter")

    env = (getattr(settings, "app_env", "") or "").strip().lower()
    allow_runtime = bool(getattr(settings, "allow_runtime_llm_overrides", False))

    if not settings.openrouter_enabled:
        # Allow runtime enabling via Redis.
        try:
            if env in {"prod", "production"} and not allow_runtime:
                if debug_out is not None:
                    debug_out.setdefault("error", "disabled")
                return []
            r = get_redis()
            enabled_raw = (r.hget("runtime:llm", "openrouter_enabled") or b"").decode("utf-8", errors="ignore")
            if enabled_raw.strip().lower() not in {"1", "true", "yes", "on"}:
                if debug_out is not None:
                    debug_out.setdefault("error", "disabled")
                return []
        except Exception:
            log.debug("generate_quiz_questions_openrouter: runtime enable check failed", exc_info=True)
            if debug_out is not None:
                debug_out.setdefault("error", "disabled")
            return []

    token = (settings.openrouter_api_key or "").strip()

    # Runtime overrides.
    runtime_model: str | None = None
    runtime_base: str | None = None
    runtime_ref: str | None = None
    runtime_title: str | None = None
    try:
        if env in {"prod", "production"} and not allow_runtime:
            raise RuntimeError("runtime_overrides_disabled")
        r = get_redis()
        rt = r.hget("runtime:llm", "openrouter_api_key")
        if rt is not None:
            token = (rt.decode("utf-8") if isinstance(rt, (bytes, bytearray)) else str(rt)).strip() or token

        rm = r.hget("runtime:llm", "openrouter_model")
        if rm is not None:
            runtime_model = (rm.decode("utf-8") if isinstance(rm, (bytes, bytearray)) else str(rm)).strip() or None

        rb = r.hget("runtime:llm", "openrouter_base_url")
        if rb is not None:
            runtime_base = (rb.decode("utf-8") if isinstance(rb, (bytes, bytearray)) else str(rb)).strip() or None

        rr = r.hget("runtime:llm", "openrouter_http_referer")
        if rr is not None:
            runtime_ref = (rr.decode("utf-8") if isinstance(rr, (bytes, bytearray)) else str(rr)).strip() or None

        rtt = r.hget("runtime:llm", "openrouter_app_title")
        if rtt is not None:
            runtime_title = (rtt.decode("utf-8") if isinstance(rtt, (bytes, bytearray)) else str(rtt)).strip() or None
    except Exception:
        log.debug("generate_quiz_questions_openrouter: runtime overrides read failed", exc_info=True)

    if not token:
        if debug_out is not None:
            debug_out["error"] = "missing_token"
        return []

    def _set_debug(error: str) -> None:
        if debug_out is None:
            return
        debug_out["error"] = error

    use_model = (
        (str(model).strip() if model is not None else "")
        or (runtime_model or "")
        or str(settings.openrouter_model or "").strip()
    )
    if not use_model:
        _set_debug("missing_model")
        return []

    sys_prompt = (
        str(system_prompt).strip()
        if system_prompt is not None and str(system_prompt).strip()
        else (
            "Ты методист и экзаменатор корпоративного обучения. Цель — контроль понимания, не формальность. "
            "Генерируй вопросы СТРОГО по тексту урока и терминам из него. "
            'Верни ТОЛЬКО JSON: {\"questions\": [...]} без Markdown. '
            "Тип только single. В prompt обязательно 4 варианта A) B) C) D) (каждый с новой строки). "
            "correct_answer: одна буква 'A'|'B'|'C'|'D' — вариант, который действительно верен по тексту. "
            "НЕЛЬЗЯ всегда отвечать 'A'. explanation обязательна: 1–2 предложения с опорой на смысл из текста."
        )
    )

    use_temp = float(temperature) if temperature is not None else float(settings.openrouter_temperature)

    payload = {
        "model": use_model,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": sys_prompt,
            },
            {
                "role": "user",
                "content": (
                    (
                        "Ты получил свой предыдущий ответ, но он не прошёл парсинг JSON. "
                        "Твоя задача — ВОССТАНОВИТЬ и ВЕРНУТЬ ТОЛЬКО валидный JSON строго по схеме: "
                        '{"questions":[{"type":"single","prompt":"...\\nA) ...\\nB) ...\\nC) ...\\nD) ...","correct_answer":"A","explanation":"..."}]}. '
                        "Нельзя добавлять Markdown/текст вокруг. Нельзя добавлять новые ключи. "
                        "Исправляй только формат/кавычки/запятые/поля, не придумывай новые вопросы. "
                        "\n\nПРЕДЫДУЩИЙ ОТВЕТ (исправь):\n"
                        + str(repair_text or "")[:24000]
                    )
                    if (repair_text is not None and str(repair_text).strip())
                    else (
                        f"Урок: {title}\n\n"
                        f"Текст урока:\n{text[:12000]}\n\n"
                        f"Сгенерируй {int(n_questions)} вопрос(а/ов) повышающей сложности. "
                        "ВНИМАНИЕ: correct_answer НЕ должен всегда быть одной и той же буквой. "
                        "Сделай ответы распределёнными (A/B/C/D)."
                    )
                ),
            },
        ],
        "temperature": use_temp,
    }

    if debug_out is not None:
        try:
            user_msg = ""
            try:
                msgs = payload.get("messages") or []
                if isinstance(msgs, list) and len(msgs) >= 2 and isinstance(msgs[1], dict):
                    user_msg = str(msgs[1].get("content") or "")
            except Exception:
                user_msg = ""
            debug_out.setdefault(
                "request",
                {
                    "provider": "openrouter",
                    "model": str(use_model),
                    "temperature": float(use_temp),
                    "timeout_read_seconds": float(timeout_read_seconds) if timeout_read_seconds is not None else None,
                    "system_prompt_snip": str(sys_prompt or "")[:1200]
                    if (bool(getattr(settings, "llm_debug_log", False)) or bool(getattr(settings, "llm_debug_save", False)))
                    else "",
                    "user_prompt_snip": str(user_msg or "")[:2400]
                    if (bool(getattr(settings, "llm_debug_log", False)) or bool(getattr(settings, "llm_debug_save", False)))
                    else "",
                    "repair": bool(repair_text and str(repair_text).strip()),
                },
            )
        except Exception:
            log.debug("generate_quiz_questions_openrouter: debug_out request metadata build failed", exc_info=True)

    base = (
        (str(base_url).strip() if base_url is not None else "")
        or (runtime_base or "")
        or str(settings.openrouter_base_url or "")
    ).rstrip("/")
    url = base + "/chat/completions"

    if not base:
        _set_debug("missing_base_url")
        return []

    headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
    referer = (runtime_ref or "") or str(settings.openrouter_http_referer or "").strip()
    app_title = (runtime_title or "") or str(settings.openrouter_app_title or "").strip()
    if referer:
        headers["HTTP-Referer"] = referer
    if app_title:
        headers["X-Title"] = app_title

    try:
        read_s = float(timeout_read_seconds) if timeout_read_seconds is not None else float(settings.openrouter_timeout_read)
        base_connect_s = float(settings.openrouter_timeout_connect)
        timeout_obj = httpx.Timeout(
            connect=base_connect_s,
            read=read_s,
            write=float(settings.openrouter_timeout_write),
            pool=3.0,
        )

        data = None
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                # Small increasing connect budget for transient network issues.
                current_timeout = httpx.Timeout(
                    connect=base_connect_s + (attempt - 1) * 2.0,
                    read=read_s,
                    write=float(settings.openrouter_timeout_write),
                    pool=3.0,
                )
                with httpx.Client(timeout=current_timeout) as client:
                    r = client.post(url, json=payload, headers=headers)
                    r.raise_for_status()
                    data = r.json()
                last_exc = None
                break
            except (httpx.ConnectTimeout, httpx.ConnectError) as e:
                last_exc = e
                if attempt < 3:
                    continue
                raise
            except httpx.ReadTimeout as e:
                last_exc = e
                raise

        if data is None and last_exc is not None:
            raise last_exc
    except Exception as e:
        status = None
        body_snip = None
        try:
            resp = getattr(e, "response", None)
            status = int(getattr(resp, "status_code", None) or 0) or None
            try:
                txt = getattr(resp, "text", None)
                if callable(txt):
                    txt = txt()
            except Exception:
                txt = None
            if isinstance(txt, str) and txt:
                body_snip = txt[:600]
        except Exception:
            status = None
            body_snip = None

        if debug_out is not None:
            if status is not None:
                debug_out["http_status"] = int(status)
            if body_snip and (bool(getattr(settings, "llm_debug_log", False)) or bool(getattr(settings, "llm_debug_save", False))):
                debug_out["http_body"] = body_snip
        _set_debug(f"request_failed:{type(e).__name__}{(':HTTP_' + str(status)) if status else ''}")
        return []

    content = None
    try:
        choices = (data or {}).get("choices") or []
        if choices:
            content = (choices[0] or {}).get("message", {}).get("content")
    except Exception:
        content = None

    raw = content if isinstance(content, str) else ""
    if debug_out is not None:
        # Keep a bounded raw snippet to aid diagnostics and repair.
        if bool(getattr(settings, "llm_debug_log", False)) or bool(getattr(settings, "llm_debug_save", False)):
            debug_out["raw"] = raw[:6000]
    obj = _extract_json(raw)
    if not obj:
        _set_debug("invalid_json")
        return []

    if debug_out is not None:
        if bool(getattr(settings, "llm_debug_log", False)) or bool(getattr(settings, "llm_debug_save", False)):
            debug_out.setdefault("raw_snip", raw[:600])
        try:
            debug_out.setdefault("json_keys", list(obj.keys()))
        except Exception:
            log.debug("generate_quiz_questions_openrouter: debug_out json_keys failed", exc_info=True)

    try:
        parsed = OpenRouterQuizResponse.model_validate(obj)
    except ValidationError:
        # Be forgiving: OpenRouter models may return slightly different schemas.
        # Try to normalize common shapes into {"questions": [{type,prompt,correct_answer,explanation}]}.
        try:
            raw_items = None
            for k in ("questions", "items", "data", "result"):
                v = obj.get(k) if isinstance(obj, dict) else None
                if isinstance(v, list):
                    raw_items = v
                    break

            if raw_items is None and isinstance(obj, dict):
                # Sometimes the model returns a single question object.
                if any(x in obj for x in ("prompt", "question")):
                    raw_items = [obj]

            normalized: list[OpenRouterQuestion] = []
            failed = 0
            for it in raw_items or []:
                if not isinstance(it, dict):
                    continue

                base_prompt = (it.get("prompt") or it.get("question") or it.get("text") or it.get("q") or "")
                opts = it.get("options")
                if opts is None:
                    opts = it.get("choices")
                if opts is None:
                    opts = it.get("variants")
                if opts is None:
                    opts = it.get("answers")
                prompt = str(base_prompt or "")
                if opts is not None:
                    prompt = prompt.strip() + _format_options_for_prompt(opts)

                correct_raw = (
                    it.get("correct_answer")
                    or it.get("answer")
                    or it.get("correct")
                    or it.get("correctOption")
                    or it.get("correct_option")
                    or it.get("correct_text")
                    or ""
                )
                correct_index = (
                    it.get("correct_index")
                    or it.get("correctIndex")
                    or it.get("correct_option_index")
                    or it.get("correctOptionIndex")
                    or it.get("answer_index")
                    or it.get("answerIndex")
                )
                correct_answer = _pick_correct_answer(correct_raw=correct_raw, correct_index=correct_index, options=opts)

                cand = {
                    "type": (it.get("type") or it.get("qtype") or it.get("question_type") or "single"),
                    "prompt": prompt,
                    "correct_answer": correct_answer,
                    "explanation": (it.get("explanation") or it.get("rationale") or it.get("reason") or None),
                }
                try:
                    q = OpenRouterQuestion.model_validate(cand)
                except Exception:
                    failed += 1
                    continue
                normalized.append(q)

            if failed and (bool(getattr(settings, "llm_debug_log", False)) or bool(getattr(settings, "llm_debug_save", False))):
                log.debug("openrouter: normalized question validation failures: %s", int(failed))

            if normalized:
                parsed = OpenRouterQuizResponse(questions=normalized)
            else:
                _set_debug("schema_validation_failed")
                return []
        except Exception:
            _set_debug("schema_validation_failed")
            return []

    out: list[OpenRouterQuestion] = []
    seen_prompts: set[str] = set()
    for q in parsed.questions[: int(n_questions)]:
        t = (q.type or "").strip().lower()
        if t != "single":
            continue
        if not q.prompt:
            continue
        if not _extract_abcd_options(str(q.prompt or "")):
            continue
        ca_raw = str(q.correct_answer or "").strip()
        # Models sometimes return 'A)' / 'a' / 'A.' etc.
        ca = (ca_raw[:1].upper() if ca_raw else "")
        if ca not in {"A", "B", "C", "D"}:
            continue
        q.correct_answer = ca

        if not _is_good_question(q, seen_prompts=seen_prompts):
            continue
        out.append(q)

    if not out:
        _set_debug("no_valid_questions")
    return out
