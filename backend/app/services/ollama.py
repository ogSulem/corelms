from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import settings


class OllamaQuestion(BaseModel):
    type: str  # single|multi
    prompt: str
    correct_answer: str
    explanation: str | None = None


class OllamaQuizResponse(BaseModel):
    questions: list[OllamaQuestion]


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


def generate_quiz_questions_ollama(
    *,
    title: str,
    text: str,
    n_questions: int = 3,
    debug_out: dict[str, Any] | None = None,
    enabled: bool | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout_read_seconds: float | None = None,
) -> list[OllamaQuestion]:
    is_enabled = bool(settings.ollama_enabled) if enabled is None else bool(enabled)
    if not is_enabled:
        return []

    use_model = (str(model).strip() if model is not None else "") or str(settings.ollama_model or "").strip()
    use_base = (str(base_url).strip() if base_url is not None else "") or str(settings.ollama_base_url or "").strip()

    payload = {
        "model": use_model,
        "stream": False,
        "keep_alive": "30m",
        "format": "json",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты методист и экзаменатор корпоративного обучения. Цель — контроль понимания, не формальность. "
                    "Генерируй вопросы СТРОГО по тексту урока и терминам из него. "
                    "Пиши ТОЛЬКО на русском языке. "
                    "Избегай тривиальных вопросов уровня 'что такое ...' без контекста — спрашивай про причины, условия, ограничения, отличия, сценарии. "
                    "Дистракторы должны быть правдоподобными и близкими по смыслу, но неверными по тексту урока. "
                    'Верни ТОЛЬКО JSON: {"questions": [...]} без Markdown и комментариев. '
                    "Типы: single или multi. В prompt обязательно 4 варианта A) B) C) D) (каждый с новой строки). "
                    "correct_answer: 'A' для single или 'A,C' для multi (буквы через запятую, без пробелов). "
                    "explanation обязательна: 1–2 предложения, почему ответ верный, с опорой на формулировку из текста."
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
    }

    url = use_base.rstrip("/") + "/api/chat"

    def _set_debug(error: str) -> None:
        if debug_out is None:
            return
        debug_out["error"] = error

    try:
        # Ollama can be slow on first tokens / under load. Use more generous timeouts and a few retries.
        read_s = float(timeout_read_seconds) if timeout_read_seconds is not None else 35.0
        timeout = httpx.Timeout(connect=4.0, read=read_s, write=20.0, pool=3.0)
        with httpx.Client(timeout=timeout) as client:
            last_exc: Exception | None = None
            for attempt in range(1, 4):
                try:
                    r = client.post(url, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    try:
                        import time

                        time.sleep(0.35 * attempt)
                    except Exception:
                        pass
                    continue
            if last_exc is not None:
                print(f"ollama: chat failed (fallback) err={type(last_exc).__name__}: {last_exc}", flush=True)
                status = None
                body_snip = None
                try:
                    resp = getattr(last_exc, "response", None)
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
                _set_debug(f"request_failed:{type(last_exc).__name__}{(':HTTP_' + str(status)) if status else ''}")
                return []
    except Exception:
        _set_debug("client_failed")
        return []

    content = None
    try:
        content = (data or {}).get("message", {}).get("content")
    except Exception:
        content = None

    raw = content if isinstance(content, str) else ""
    obj = _extract_json(raw)
    if not obj:
        _set_debug("invalid_json")
        return []

    try:
        parsed = OllamaQuizResponse.model_validate(obj)
    except ValidationError:
        _set_debug("schema_validation_failed")
        return []

    out: list[OllamaQuestion] = []
    for q in parsed.questions[: int(n_questions)]:
        t = (q.type or "").strip().lower()
        if t not in {"single", "multi"}:
            continue
        if not q.prompt or "A)" not in q.prompt:
            continue
        if not q.correct_answer:
            continue
        if t == "multi":
            ca = str(q.correct_answer or "")
            # Basic sanity: multi answer should include at least one comma-separated option.
            # Example: "A,C".
            if "," not in ca:
                continue
        if not q.explanation or not str(q.explanation).strip():
            continue
        out.append(q)

    return out


def ollama_healthcheck(*, enabled: bool | None = None, base_url: str | None = None) -> tuple[bool, str | None]:
    is_enabled = bool(settings.ollama_enabled) if enabled is None else bool(enabled)
    if not is_enabled:
        return False, "disabled"

    use_base = (str(base_url).strip() if base_url is not None else "") or str(settings.ollama_base_url or "").strip()
    url = use_base.rstrip("/") + "/api/tags"
    try:
        with httpx.Client(timeout=2.5) as client:
            r = client.get(url)
            if r.status_code >= 400:
                snip = ""
                try:
                    snip = (r.text or "")[:200]
                except Exception:
                    snip = ""
                return False, f"http_{r.status_code}" + (f":{snip}" if snip else "")
        return True, None
    except Exception as e:
        msg = ""
        try:
            msg = str(e)[:200]
        except Exception:
            msg = ""
        return False, f"unreachable:{type(e).__name__}" + (f":{msg}" if msg else "") + f" url={url}"


def ollama_chat_preflight(
    *,
    enabled: bool | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout_s: float = 2.2,
) -> tuple[bool, str | None]:
    """Real preflight that hits /api/chat with a tiny prompt.

    This catches cases where Ollama is reachable (/api/tags OK) but chat
    requests hang or the model is overloaded.
    """

    is_enabled = bool(settings.ollama_enabled) if enabled is None else bool(enabled)
    if not is_enabled:
        return False, "disabled"

    use_model = (str(model).strip() if model is not None else "") or str(settings.ollama_model or "").strip()
    use_base = (str(base_url).strip() if base_url is not None else "") or str(settings.ollama_base_url or "").strip()
    if not use_model:
        return False, "no_model"
    if not use_base:
        return False, "no_base_url"

    url = use_base.rstrip("/") + "/api/chat"
    payload = {
        "model": use_model,
        "stream": False,
        "keep_alive": "30s",
        "messages": [
            {"role": "system", "content": "Ответь одним словом: OK"},
            {"role": "user", "content": "ping"},
        ],
    }

    try:
        timeout = httpx.Timeout(connect=1.2, read=float(timeout_s), write=2.0, pool=1.2)
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, json=payload)
            if r.status_code >= 400:
                snip = ""
                try:
                    snip = (r.text or "")[:200]
                except Exception:
                    snip = ""
                return False, f"http_{r.status_code}" + (f":{snip}" if snip else "")
            # Any JSON body is enough; we only care about responsiveness.
            return True, None
    except Exception as e:
        msg = ""
        try:
            msg = str(e)[:200]
        except Exception:
            msg = ""
        return False, f"chat_unreachable:{type(e).__name__}" + (f":{msg}" if msg else "") + f" url={url}"
