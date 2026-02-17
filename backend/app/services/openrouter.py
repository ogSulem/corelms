from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.redis_client import get_redis


class OpenRouterQuestion(BaseModel):
    type: str
    prompt: str
    correct_answer: str
    explanation: str | None = None


class OpenRouterQuizResponse(BaseModel):
    questions: list[OpenRouterQuestion]


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


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None

    s = text.strip()
    if s.startswith("{") and s.endswith("}"):
        try:
            return json.loads(s)
        except Exception:
            pass

    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        return None

    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def generate_quiz_questions_openrouter(
    *,
    title: str,
    text: str,
    n_questions: int = 3,
    debug_out: dict[str, Any] | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> list[OpenRouterQuestion]:
    if not settings.openrouter_enabled:
        # Allow runtime enabling via Redis.
        try:
            r = get_redis()
            enabled_raw = (r.hget("runtime:llm", "openrouter_enabled") or b"").decode("utf-8", errors="ignore")
            if enabled_raw.strip().lower() not in {"1", "true", "yes", "on"}:
                return []
        except Exception:
            return []

    token = (settings.openrouter_api_key or "").strip()

    # Runtime overrides.
    runtime_model: str | None = None
    runtime_base: str | None = None
    runtime_ref: str | None = None
    runtime_title: str | None = None
    try:
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
        pass

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

    payload = {
        "model": use_model,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты методист и экзаменатор корпоративного обучения. Цель — контроль понимания, не формальность. "
                    "Генерируй вопросы СТРОГО по тексту урока и терминам из него. "
                    'Верни ТОЛЬКО JSON: {"questions": [...]} без Markdown. '
                    "Тип только single. В prompt обязательно 4 варианта A) B) C) D) (каждый с новой строки). "
                    "correct_answer: одна буква 'A'|'B'|'C'|'D' — вариант, который действительно верен по тексту. "
                    "НЕЛЬЗЯ всегда отвечать 'A'. explanation обязательна: 1–2 предложения с опорой на смысл из текста."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Урок: {title}\n\n" f"Текст урока:\n{text[:12000]}\n\n" f"Сгенерируй {int(n_questions)} вопрос(а/ов)."
                ),
            },
        ],
        "temperature": float(settings.openrouter_temperature),
    }

    base = (
        (str(base_url).strip() if base_url is not None else "")
        or (runtime_base or "")
        or str(settings.openrouter_base_url or "")
    ).rstrip("/")
    url = base + "/chat/completions"

    headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
    referer = (runtime_ref or "") or str(settings.openrouter_http_referer or "").strip()
    app_title = (runtime_title or "") or str(settings.openrouter_app_title or "").strip()
    if referer:
        headers["HTTP-Referer"] = referer
    if app_title:
        headers["X-Title"] = app_title

    try:
        timeout = httpx.Timeout(
            connect=float(settings.openrouter_timeout_connect),
            read=float(settings.openrouter_timeout_read),
            write=float(settings.openrouter_timeout_write),
            pool=3.0,
        )
        data = None
        last_err: Exception | None = None
        with httpx.Client(timeout=timeout) as client:
            for _attempt in range(1, 4):
                try:
                    r = client.post(url, json=payload, headers=headers)
                    r.raise_for_status()
                    data = r.json()
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    continue
        if data is None:
            raise last_err or RuntimeError("request_failed")
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
            if body_snip:
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
    obj = _extract_json(raw)
    if not obj:
        _set_debug("invalid_json")
        return []

    if debug_out is not None:
        debug_out.setdefault("raw_snip", raw[:600])
        try:
            debug_out.setdefault("json_keys", list(obj.keys()))
        except Exception:
            pass

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
            for it in raw_items or []:
                if not isinstance(it, dict):
                    continue

                base_prompt = (it.get("prompt") or it.get("question") or it.get("text") or "")
                opts = it.get("options")
                if opts is None:
                    opts = it.get("choices")
                prompt = str(base_prompt or "")
                if opts is not None:
                    prompt = prompt.strip() + _format_options_for_prompt(opts)

                cand = {
                    "type": (it.get("type") or it.get("qtype") or it.get("question_type") or "single"),
                    "prompt": prompt,
                    "correct_answer": (
                        it.get("correct_answer")
                        or it.get("answer")
                        or it.get("correct")
                        or it.get("correctOption")
                        or ""
                    ),
                    "explanation": (it.get("explanation") or it.get("rationale") or it.get("reason") or None),
                }
                try:
                    q = OpenRouterQuestion.model_validate(cand)
                except Exception:
                    continue
                normalized.append(q)

            if normalized:
                parsed = OpenRouterQuizResponse(questions=normalized)
            else:
                _set_debug("schema_validation_failed")
                return []
        except Exception:
            _set_debug("schema_validation_failed")
            return []

    out: list[OpenRouterQuestion] = []
    for q in parsed.questions[: int(n_questions)]:
        t = (q.type or "").strip().lower()
        if t != "single":
            continue
        if not q.prompt:
            continue
        if "A)" not in q.prompt or "B)" not in q.prompt or "C)" not in q.prompt or "D)" not in q.prompt:
            continue
        ca_raw = str(q.correct_answer or "").strip()
        # Models sometimes return 'A)' / 'a' / 'A.' etc.
        ca = (ca_raw[:1].upper() if ca_raw else "")
        if ca not in {"A", "B", "C", "D"}:
            continue
        q.correct_answer = ca

        # Explanation improves quality but should not block question delivery.
        if not q.explanation or not str(q.explanation).strip():
            q.explanation = None
        out.append(q)

    if not out:
        _set_debug("no_valid_questions")
    return out
