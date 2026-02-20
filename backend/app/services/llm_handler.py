from __future__ import annotations

import time
import re
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
    min_questions: int | None = None,
    retries: int = 1,
    backoff_seconds: float = 0.8,
    debug_out: dict[str, Any] | None = None,
    provider_order: list[str] | None = None,
    time_budget_seconds: float | None = None,
) -> list[Any]:
    """Unified LLM handler with fallback.

    Returns questions with fields: type, prompt, correct_answer, explanation.
    """

    def _clean(s: object) -> str:
        return re.sub(r"\s+", " ", str(s or "").strip()).strip()

    def _extract_abcd_options(prompt: str) -> list[str] | None:
        if not prompt:
            return None
        lines = [ln.strip() for ln in str(prompt).splitlines() if ln.strip()]
        opts: dict[str, str] = {}
        for ln in lines:
            if len(ln) < 3:
                continue
            # Accept common option formats: A) / A. / A - / A:
            head2 = ln[:2].upper()
            head3 = ln[:3].upper() if len(ln) >= 3 else head2
            key = ""
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
            try:
                if key and val:
                    opts[key] = val
            except Exception:
                continue
        if all(k in opts for k in ("A", "B", "C", "D")):
            return [opts["A"], opts["B"], opts["C"], opts["D"]]
        return None

    def _norm_correct_answer(raw: str) -> str:
        s = _clean(raw).upper()
        if not s:
            return ""
        # Allow "A" / "A)" / "A." / "A," etc.
        ch = s[:1]
        return ch if ch in {"A", "B", "C", "D"} else ""

    def _is_valid_question(q: Any, *, seen_prompts: set[str]) -> bool:
        raw_type = _clean(getattr(q, "type", "") or "single").lower()
        if raw_type not in {"single", "multi", "case"}:
            return False

        prompt = str(getattr(q, "prompt", "") or "").strip()
        if len(_clean(prompt)) < 18:
            return False

        norm_p = _clean(prompt).lower()
        if norm_p in seen_prompts:
            return False

        opts = _extract_abcd_options(prompt)
        if not opts:
            return False

        norm_opts = [_clean(o).lower() for o in opts]
        if len({o for o in norm_opts if o}) != 4:
            return False
        if any(len(o) < 2 for o in norm_opts):
            return False

        ca_raw = _clean(getattr(q, "correct_answer", ""))
        if raw_type == "multi":
            # Format: A,C (letters, comma-separated, no spaces)
            parts = [p.strip().upper() for p in ca_raw.split(",") if p.strip()]
            if len(parts) < 2:
                return False
            if any(p not in {"A", "B", "C", "D"} for p in parts):
                return False
        else:
            if _norm_correct_answer(ca_raw) not in {"A", "B", "C", "D"}:
                return False

        exp = _clean(getattr(q, "explanation", ""))
        if len(exp) < 6:
            return False

        seen_prompts.add(norm_p)
        return True

    def _filter_questions(items: list[Any], *, want: int) -> list[Any]:
        seen: set[str] = set()
        out: list[Any] = []
        for q in items or []:
            if _is_valid_question(q, seen_prompts=seen):
                out.append(q)
            if len(out) >= want:
                break
        return out

    def _is_degenerate(items: list[Any]) -> bool:
        # Reject common failure mode where model returns correct_answer always 'A' or always same.
        if not items or len(items) < 3:
            return False
        answers: list[str] = []
        for q in items:
            ca = _clean(getattr(q, "correct_answer", ""))
            if not ca:
                continue
            answers.append(ca[:1].upper())
        if len(answers) < 3:
            return False
        return len(set(answers)) <= 1

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

    # Product configuration: OpenRouter-only.
    # Ignore other providers even if configured.
    order = ["openrouter"]

    errors: list[str] = []

    t_start = time.monotonic()
    budget_s = float(time_budget_seconds) if time_budget_seconds is not None else None
    if debug_out is not None:
        debug_out.setdefault("time_budget_seconds", budget_s)

    def _remaining_s() -> float | None:
        if budget_s is None:
            return None
        return max(0.0, budget_s - (time.monotonic() - t_start))

    def _budget_exhausted() -> bool:
        rem = _remaining_s()
        return rem is not None and rem <= 0.0

    def _cap_tries_by_budget(*, rem_s: float | None, per_attempt_s: float, max_tries_in: int) -> int:
        if rem_s is None:
            return max_tries_in
        # Reserve small overhead per attempt (json parsing, retries, etc.)
        cost = max(1.0, float(per_attempt_s) + 1.0)
        return max(1, min(int(max_tries_in), int(rem_s // cost) + 1))

    want = int(n_questions or 0)
    min_q = int(min_questions) if min_questions is not None else want
    min_q = max(1, min(min_q, want if want > 0 else min_q))
    max_tries = max(1, min(int(retries or 1), 8))

    for provider in order:
        try:
            if _budget_exhausted():
                errors.append("budget_exhausted")
                break

            if provider in {"openrouter", "or"}:
                if not (bool(settings.openrouter_enabled) or bool(runtime_or_enabled)):
                    continue
                ok_or, _meta = (False, None)
                try:
                    ok_or, _meta = openrouter_healthcheck()
                except Exception:
                    ok_or = False

                local_debug = {}
                best: list[Any] = []
                best_valid: list[Any] = []
                last_err = None

                strict_prompt = (
                    "Ты методист и экзаменатор. Верни ТОЛЬКО валидный JSON без Markdown и без текста вокруг. "
                    "Язык: русский. Структура строго: {\"questions\":[{" 
                    "\"type\":\"single\",\"prompt\":\"...\\nA) ...\\nB) ...\\nC) ...\\nD) ...\"," 
                    "\"correct_answer\":\"A\",\"explanation\":\"...\"}]}. "
                    "В prompt обязательно 4 варианта A) B) C) D) (каждый с новой строки). "
                    "correct_answer: строго одна буква A|B|C|D. "
                    "НЕ допускай, чтобы correct_answer всегда был один и тот же. Разноси ответы по буквам. "
                    "Вопросы должны проверять смысл, а не формальность. explanation: 1-2 предложения с опорой на текст. "
                    "Никаких ссылок на внешние знания: только по данному тексту."
                )

                # Each OpenRouter attempt may take up to its read timeout.
                # Cap attempts so we stay within the overall budget.
                rem = _remaining_s()
                per_attempt = float(getattr(settings, "openrouter_timeout_read", 15.0) or 15.0)
                cap_tries = _cap_tries_by_budget(rem_s=rem, per_attempt_s=per_attempt, max_tries_in=max_tries)
                for attempt in range(1, cap_tries + 1):
                    if _budget_exhausted():
                        last_err = "budget_exhausted"
                        break
                    local_debug = {}
                    rem_call = _remaining_s()
                    dyn_read = None
                    try:
                        if rem_call is not None:
                            dyn_read = max(3.0, min(per_attempt, float(rem_call) - 1.0))
                    except Exception:
                        dyn_read = None
                    out = generate_quiz_questions_openrouter(
                        title=title,
                        text=text,
                        n_questions=n_questions,
                        debug_out=local_debug,
                        base_url=runtime_or_base_url,
                        model=runtime_or_model,
                        system_prompt=strict_prompt,
                        temperature=0.2,
                        timeout_read_seconds=dyn_read,
                    )
                    valid = _filter_questions(list(out or []), want=want)
                    if valid and _is_degenerate(valid):
                        valid = []
                        local_debug["error"] = "degenerate_answers"

                    # Repair step: if provider returned near-JSON but failed validation/parsing.
                    # Use its own raw output and ask for strict JSON only.
                    if (not valid) and attempt < cap_tries:
                        raw = str(local_debug.get("raw") or "").strip()
                        if raw and len(raw) >= 20 and str(local_debug.get("error") or "") in {"invalid_json", "schema_validation_failed", "no_valid_questions"}:
                            repair_debug: dict[str, object] = {}
                            repaired = generate_quiz_questions_openrouter(
                                title=title,
                                text=text,
                                n_questions=n_questions,
                                debug_out=repair_debug,
                                base_url=runtime_or_base_url,
                                model=runtime_or_model,
                                system_prompt=strict_prompt,
                                temperature=0.0,
                                timeout_read_seconds=dyn_read,
                                repair_text=raw,
                            )
                            repaired_valid = _filter_questions(list(repaired or []), want=want)
                            if repaired_valid and not _is_degenerate(repaired_valid):
                                valid = repaired_valid
                                local_debug["repair_used"] = True
                                local_debug["repair_error"] = str(repair_debug.get("error") or "")

                    if valid and len(valid) >= min_q:
                        _set_debug("provider", "openrouter")
                        _set_debug("provider_error", None)
                        if debug_out is not None:
                            debug_out.setdefault("openrouter_attempts", attempt)
                        return valid

                    if valid and len(valid) > len(best_valid):
                        best_valid = valid
                    if out and len(out) > len(best):
                        best = list(out)
                    last_err = str(local_debug.get("error") or "empty")

                    if not ok_or:
                        break
                    if attempt < max_tries:
                        time.sleep(max(0.1, float(backoff_seconds) * float(attempt)))

                if best_valid and len(best_valid) >= min_q:
                    _set_debug("provider", "openrouter")
                    _set_debug("provider_error", None)
                    return best_valid
                errors.append("openrouter:" + str(last_err or "empty"))
                continue

            if provider == "ollama":
                rem = _remaining_s()
                # Ollama can block up to its internal timeouts. Skip if we don't have enough budget.
                per_attempt = 35.0
                try:
                    per_attempt = float(getattr(settings, "ollama_timeout_read", 35.0) or 35.0)
                except Exception:
                    per_attempt = 35.0
                if rem is not None and rem < max(6.0, per_attempt * 0.75):
                    errors.append("ollama:skipped_budget")
                    continue
                eff_ollama_enabled = bool(settings.ollama_enabled) if runtime_ollama_enabled is None else bool(runtime_ollama_enabled)
                if not eff_ollama_enabled:
                    continue
                best_valid: list[Any] = []
                last_err = None
                rem = _remaining_s()
                cap_tries = _cap_tries_by_budget(rem_s=rem, per_attempt_s=per_attempt, max_tries_in=max_tries)
                for attempt in range(1, cap_tries + 1):
                    if _budget_exhausted():
                        last_err = "budget_exhausted"
                        break
                    local_debug = {}
                    rem_call = _remaining_s()
                    dyn_read = None
                    try:
                        if rem_call is not None:
                            dyn_read = max(4.0, min(per_attempt, float(rem_call) - 1.0))
                    except Exception:
                        dyn_read = None

                    out = generate_quiz_questions_ollama(
                        title=title,
                        text=text,
                        n_questions=n_questions,
                        debug_out=local_debug,
                        enabled=eff_ollama_enabled,
                        base_url=runtime_ollama_base_url,
                        model=runtime_ollama_model,
                        timeout_read_seconds=dyn_read,
                    )
                    valid = _filter_questions(list(out or []), want=want)
                    if valid and _is_degenerate(valid):
                        valid = []
                        local_debug["error"] = "degenerate_answers"

                    if valid and len(valid) > len(best_valid):
                        best_valid = valid
                    if valid and len(valid) >= min_q:
                        _set_debug("provider", "ollama")
                        _set_debug("provider_error", None)
                        if debug_out is not None:
                            debug_out.setdefault("ollama_attempts", attempt)
                        return valid

                    last_err = str(local_debug.get("error") or "empty")
                    if attempt < cap_tries:
                        time.sleep(max(0.1, float(backoff_seconds) * float(attempt)))

                if best_valid and len(best_valid) >= min_q:
                    _set_debug("provider", "ollama")
                    _set_debug("provider_error", None)
                    return best_valid

                errors.append("ollama:" + str(last_err or "empty"))
                continue

            if provider in {"hf", "hf_router"}:
                rem = _remaining_s()
                per_attempt = float(getattr(settings, "hf_router_timeout_read", 12.0) or 12.0)
                if rem is not None and rem < max(4.0, per_attempt * 0.75):
                    errors.append("hf_router:skipped_budget")
                    continue
                if not (bool(settings.hf_router_enabled) or bool(runtime_hf_enabled)):
                    continue
                best_valid: list[Any] = []
                last_err = None
                rem = _remaining_s()
                cap_tries = _cap_tries_by_budget(rem_s=rem, per_attempt_s=per_attempt, max_tries_in=max_tries)
                for attempt in range(1, cap_tries + 1):
                    if _budget_exhausted():
                        last_err = "budget_exhausted"
                        break
                    local_debug = {}
                    rem_call = _remaining_s()
                    dyn_read = None
                    try:
                        if rem_call is not None:
                            dyn_read = max(3.0, min(per_attempt, float(rem_call) - 1.0))
                    except Exception:
                        dyn_read = None

                    out = generate_quiz_questions_hf_router(
                        title=title,
                        text=text,
                        n_questions=n_questions,
                        debug_out=local_debug,
                        base_url=runtime_hf_base_url,
                        model=runtime_hf_model,
                        timeout_read_seconds=dyn_read,
                    )
                    valid = _filter_questions(list(out or []), want=want)
                    if valid and _is_degenerate(valid):
                        valid = []
                        local_debug["error"] = "degenerate_answers"

                    if valid and len(valid) > len(best_valid):
                        best_valid = valid
                    if valid and len(valid) >= min_q:
                        _set_debug("provider", "hf_router")
                        _set_debug("provider_error", None)
                        if debug_out is not None:
                            debug_out.setdefault("hf_router_attempts", attempt)
                        return valid

                    last_err = str(local_debug.get("error") or "empty")
                    if attempt < cap_tries:
                        time.sleep(max(0.1, float(backoff_seconds) * float(attempt)))

                if best_valid and len(best_valid) >= min_q:
                    _set_debug("provider", "hf_router")
                    _set_debug("provider_error", None)
                    return best_valid

                errors.append("hf_router:" + str(last_err or "empty"))
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
    # Product configuration: OpenRouter-only.
    # Keep signature for backward compatibility.
    return ["openrouter"]
