from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.redis_client import get_redis


class HfQuestion(BaseModel):
    type: str
    prompt: str
    correct_answer: str
    explanation: str | None = None


class HfQuizResponse(BaseModel):
    questions: list[HfQuestion]


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


def generate_quiz_questions_hf_router(
    *,
    title: str,
    text: str,
    n_questions: int = 3,
    debug_out: dict[str, Any] | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout_read_seconds: float | None = None,
) -> list[HfQuestion]:
    if not settings.hf_router_enabled:
        # Allow runtime enabling via Redis.
        try:
            r = get_redis()
            enabled_raw = (r.hget("runtime:llm", "hf_router_enabled") or b"").decode("utf-8", errors="ignore")
            if enabled_raw.strip().lower() not in {"1", "true", "yes", "on"}:
                return []
        except Exception:
            return []

    token = (settings.hf_router_token or "").strip()
    # Runtime token override.
    try:
        r = get_redis()
        rt = r.hget("runtime:llm", "hf_router_token")
        if rt is not None:
            token = (rt.decode("utf-8") if isinstance(rt, (bytes, bytearray)) else str(rt)).strip() or token
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

    use_model = (str(model).strip() if model is not None else "") or str(settings.hf_router_model or "").strip()
    payload = {
        "model": use_model,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты методист и экзаменатор корпоративного обучения. Цель — контроль понимания, не формальность. "
                    "Генерируй вопросы СТРОГО по тексту урока и терминам из него. "
                    "Верни ТОЛЬКО JSON: {\"questions\": [...]} без Markdown. "
                    "Тип только single. В prompt обязательно 4 варианта A) B) C) D) (каждый с новой строки). "
                    "correct_answer: одна буква 'A'|'B'|'C'|'D' — вариант, который действительно верен по тексту. "
                    "НЕЛЬЗЯ всегда отвечать 'A'. explanation обязательна: 1–2 предложения с ссылкой на смысл из текста."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Урок: {title}\n\n"
                    f"Текст урока:\n{text[:12000]}\n\n"
                    f"Сгенерируй {int(n_questions)} вопрос(а/ов) повышающей сложности."
                ),
            },
        ],
        "temperature": float(settings.hf_router_temperature),
    }

    base = ((str(base_url).strip() if base_url is not None else "") or str(settings.hf_router_base_url or "")).rstrip("/")
    url = base + "/chat/completions"

    try:
        read_s = float(timeout_read_seconds) if timeout_read_seconds is not None else float(settings.hf_router_timeout_read)
        timeout = httpx.Timeout(
            connect=float(settings.hf_router_timeout_connect),
            read=read_s,
            write=float(settings.hf_router_timeout_write),
            pool=3.0,
        )
        data = None
        last_err: Exception | None = None
        with httpx.Client(timeout=timeout) as client:
            for attempt in range(1, 4):
                try:
                    r = client.post(
                        url,
                        json=payload,
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    r.raise_for_status()
                    data = r.json()
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    # best-effort: continue retries
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

    try:
        parsed = HfQuizResponse.model_validate(obj)
    except ValidationError:
        _set_debug("schema_validation_failed")
        return []

    out: list[HfQuestion] = []
    for q in parsed.questions[: int(n_questions)]:
        t = (q.type or "").strip().lower()
        if t != "single":
            continue
        if not q.prompt:
            continue
        if "A)" not in q.prompt or "B)" not in q.prompt or "C)" not in q.prompt or "D)" not in q.prompt:
            continue
        if not q.correct_answer or (q.correct_answer or "").strip() not in {"A", "B", "C", "D"}:
            continue
        if not q.explanation or not str(q.explanation).strip():
            continue
        out.append(q)

    if not out:
        _set_debug("no_valid_questions")
    return out
