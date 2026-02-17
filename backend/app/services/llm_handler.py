from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.redis_client import get_redis
from app.services.hf_router import generate_quiz_questions_hf_router
from app.services.ollama import generate_quiz_questions_ollama, ollama_chat_preflight, ollama_healthcheck
from app.services.hf_router_health import hf_router_healthcheck
from app.services.openrouter import generate_quiz_questions_openrouter
from app.services.openrouter_health import openrouter_healthcheck


def generate_quiz_questions_ai(
    *,
    title: str,
    text: str,
    n_questions: int = 3,
    debug_out: dict[str, Any] | None = None,
    provider_order: list[str] | None = None,
) -> list[Any]:
    """Unified LLM handler with fallback.

    Returns questions with fields: type, prompt, correct_answer, explanation.
    """

    def _set_debug(key: str, value: object) -> None:
        if debug_out is None:
            return
        debug_out[key] = value

    # Runtime overrides (admin diagnostics tab) stored in Redis.
    runtime: dict[str, str] = {}
    try:
        r = get_redis()
        raw = r.hgetall("runtime:llm") or {}
        for k, v in (raw or {}).items():
            kk = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)
            vv = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
            runtime[kk] = vv
    except Exception:
        runtime = {}

    runtime_order = (runtime.get("llm_provider_order") or "").strip()
    runtime_ollama_enabled_raw = (runtime.get("ollama_enabled") or "").strip().lower()
    runtime_ollama_enabled = runtime_ollama_enabled_raw in {"1", "true", "yes", "on"} if runtime_ollama_enabled_raw else None
    runtime_ollama_base_url = (runtime.get("ollama_base_url") or "").strip() or None
    runtime_ollama_model = (runtime.get("ollama_model") or "").strip() or None

    runtime_hf_enabled = (runtime.get("hf_router_enabled") or "").strip().lower() in {"1", "true", "yes", "on"}
    runtime_hf_base_url = (runtime.get("hf_router_base_url") or "").strip() or None
    runtime_hf_model = (runtime.get("hf_router_model") or "").strip() or None

    runtime_or_enabled = (runtime.get("openrouter_enabled") or "").strip().lower() in {"1", "true", "yes", "on"}
    runtime_or_base_url = (runtime.get("openrouter_base_url") or "").strip() or None
    runtime_or_model = (runtime.get("openrouter_model") or "").strip() or None

    if provider_order is not None:
        order = [str(s).strip().lower() for s in (provider_order or []) if str(s).strip()]
    else:
        order_src = runtime_order if runtime_order else str(settings.llm_provider_order or "")
        order = [s.strip().lower() for s in str(order_src).split(",") if s.strip()]
    if not order:
        order = ["openrouter", "hf_router", "ollama"]

    errors: list[str] = []

    for provider in order:
        try:
            if provider in {"openrouter", "or"}:
                if not (bool(settings.openrouter_enabled) or bool(runtime_or_enabled)):
                    continue
                local_debug = {}
                out = generate_quiz_questions_openrouter(
                    title=title,
                    text=text,
                    n_questions=n_questions,
                    debug_out=local_debug,
                    base_url=runtime_or_base_url,
                    model=runtime_or_model,
                )
                if out:
                    _set_debug("provider", "openrouter")
                    _set_debug("provider_error", None)
                    return out
                errors.append("openrouter:" + str(local_debug.get("error") or "empty"))
                continue

            if provider == "ollama":
                eff_ollama_enabled = bool(settings.ollama_enabled) if runtime_ollama_enabled is None else bool(runtime_ollama_enabled)
                if not eff_ollama_enabled:
                    continue
                local_debug: dict[str, object] = {}
                out = generate_quiz_questions_ollama(
                    title=title,
                    text=text,
                    n_questions=n_questions,
                    debug_out=local_debug,
                    enabled=eff_ollama_enabled,
                    base_url=runtime_ollama_base_url,
                    model=runtime_ollama_model,
                )
                if out:
                    _set_debug("provider", "ollama")
                    _set_debug("provider_error", None)
                    return out
                errors.append("ollama:" + str(local_debug.get("error") or "empty"))
                continue

            if provider in {"hf", "hf_router"}:
                if not (bool(settings.hf_router_enabled) or bool(runtime_hf_enabled)):
                    continue
                local_debug = {}
                out = generate_quiz_questions_hf_router(
                    title=title,
                    text=text,
                    n_questions=n_questions,
                    debug_out=local_debug,
                    base_url=runtime_hf_base_url,
                    model=runtime_hf_model,
                )
                if out:
                    _set_debug("provider", "hf_router")
                    _set_debug("provider_error", None)
                    return out
                errors.append("hf_router:" + str(local_debug.get("error") or "empty"))
                continue
        except Exception as e:
            errors.append(provider + ":" + type(e).__name__)
            continue

    _set_debug("provider", None)
    _set_debug("provider_error", ";".join(errors) if errors else "no_provider")
    if debug_out is not None and "error" not in debug_out:
        debug_out["error"] = "all_failed"
    return []


def choose_llm_provider_order_fast(*, ttl_seconds: int = 300, use_cache: bool = True) -> list[str]:
    """Fast preflight: pick provider order based on quick healthchecks.

    Cached in Redis to avoid spamming external calls during large imports.
    """

    key = "runtime:llm_preflight_order"
    if use_cache:
        try:
            r = get_redis()
            cached = r.get(key)
            if cached:
                s = cached.decode("utf-8", errors="ignore") if isinstance(cached, (bytes, bytearray)) else str(cached)
                order = [x.strip().lower() for x in s.split(",") if x.strip()]
                if order:
                    return order
        except Exception:
            pass

    order: list[str] = []

    ok_ollama, _ = (False, None)
    ok_hf, _ = (False, None)
    ok_or, _ = (False, None)
    try:
        # Prefer a real /api/chat preflight so we don't pick Ollama when it is reachable but times out on chat.
        ok_ollama, _ = ollama_chat_preflight(enabled=bool(settings.ollama_enabled), timeout_s=2.2)
    except Exception:
        ok_ollama = False
    try:
        ok_or, _ = openrouter_healthcheck()
    except Exception:
        ok_or = False
    try:
        ok_hf, _ = hf_router_healthcheck()
    except Exception:
        ok_hf = False

    if ok_or:
        order.append("openrouter")
    if ok_ollama:
        order.append("ollama")
    if ok_hf:
        order.append("hf_router")
    if not order:
        order = ["openrouter", "hf_router", "ollama"]

    if use_cache:
        try:
            r = get_redis()
            r.set(key, ",".join(order), ex=int(ttl_seconds))
        except Exception:
            pass

    return order
