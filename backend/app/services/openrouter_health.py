from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.services.app_settings import get_ai_settings

log = logging.getLogger(__name__)

MODELS_TIMEOUT = httpx.Timeout(connect=4.0, read=8.0, write=4.0, pool=4.0)


@dataclass(frozen=True)
class AIProbeResult:
    ok: bool
    reason: str | None = None
    http_status: int | None = None
    models: list[str] | None = None
    model_available: bool | None = None
    message: str | None = None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "http_status": self.http_status,
            "model_available": self.model_available,
            "models_checked": len(self.models or []),
            "models_sample": (self.models or [])[:15],
            "message": self.message,
        }


def _models(base: str, token: str) -> tuple[int, list[str]]:
    response = httpx.get(base + "/models", headers={"Authorization": f"Bearer {token}"}, timeout=MODELS_TIMEOUT)
    names: list[str] = []
    try:
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        for item in rows or []:
            if isinstance(item, dict) and item.get("id"):
                names.append(str(item["id"]))
    except ValueError:
        names = []
    return int(response.status_code), names


def probe_ai_connection(*, api_key: str, base_url: str, model: str | None = None) -> AIProbeResult:
    """Verify a token without paying for a completion.

    OpenRouter's ``/models`` list is public, so an authenticated ``/key`` call is
    used there. Other OpenAI-compatible gateways are checked through ``/models``
    with the token; if a gateway does not expose it, generation can still be
    saved and tested by creating the first draft.
    """
    token = str(api_key or "").strip()
    base = str(base_url or "").strip().rstrip("/")
    if not token:
        return AIProbeResult(False, "missing_token", message="Введите API-токен")
    if not base:
        return AIProbeResult(False, "missing_base_url", message="Укажите адрес API")

    host = ""
    try:
        host = (urlsplit(base).hostname or "").lower()
    except ValueError:
        pass
    is_openrouter = host.endswith("openrouter.ai")

    try:
        if is_openrouter:
            response = httpx.get(base + "/key", headers={"Authorization": f"Bearer {token}"}, timeout=MODELS_TIMEOUT)
            status = int(response.status_code)
            if status in {401, 403}:
                return AIProbeResult(False, f"http_{status}", http_status=status,
                                     message="OpenRouter отклонил ключ. Скопируйте токен ещё раз из личного кабинета.")
            if status >= 400:
                return AIProbeResult(False, f"http_{status}", http_status=status,
                                     message=f"OpenRouter ответил HTTP {status}. Проверьте токен и адрес API.")
            models_status, names = _models(base, token)
        else:
            models_status, names = _models(base, token)
            status = models_status
            if status in {401, 403}:
                return AIProbeResult(False, f"http_{status}", http_status=status,
                                     message="Токен отклонён сервером. Проверьте ключ и права доступа.")
            if status == 404:
                return AIProbeResult(False, "models_endpoint_missing", http_status=status,
                                     message="Endpoint /models недоступен. Укажите базовый адрес вида https://host/api/v1.")
            if status >= 400:
                return AIProbeResult(False, f"http_{status}", http_status=status,
                                     message=f"Сервер ответил HTTP {status}. Проверьте адрес API и токен.")

        wanted = str(model or "").strip()
        available = (wanted in names) if (wanted and names) else None
        if is_openrouter:
            message = "Ключ OpenRouter принят."
        else:
            message = "Подключение работает."
        if names:
            message += f" Доступно моделей: {len(names)}."
        if available is False:
            message += f" Модель «{wanted}» не найдена в списке — проверьте имя или выберите другую."
        elif available is True:
            message += f" Модель «{wanted}» доступна."
        return AIProbeResult(True, None, http_status=status, models=names, model_available=available, message=message)
    except Exception as exc:  # network/DNS/TLS/timeouts
        return AIProbeResult(False, f"unreachable:{type(exc).__name__}",
                             message="Сервер AI недоступен. Проверьте адрес API и сеть.")


@dataclass(frozen=True)
class AIModelsResult:
    """Catalogue of models a gateway actually offers to this token."""

    ok: bool
    reason: str | None = None
    http_status: int | None = None
    models: list[dict] | None = None
    message: str | None = None

    def as_dict(self) -> dict:
        rows = self.models or []
        return {
            "ok": self.ok,
            "reason": self.reason,
            "http_status": self.http_status,
            "count": len(rows),
            "free_count": sum(1 for row in rows if row.get("free")),
            "models": rows,
            "message": self.message,
        }


def _price_is_zero(value: object) -> bool:
    try:
        return float(str(value).strip() or "0") == 0.0
    except (TypeError, ValueError):
        return False


def _model_catalogue(base: str, token: str) -> tuple[int, list[dict]]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = httpx.get(base + "/models", headers=headers, timeout=MODELS_TIMEOUT)
    rows: list[dict] = []
    try:
        payload = response.json()
        items = payload.get("data") if isinstance(payload, dict) else payload
    except ValueError:
        return int(response.status_code), []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        free = bool(pricing) and _price_is_zero(pricing.get("prompt")) and _price_is_zero(pricing.get("completion"))
        rows.append({
            "id": str(item["id"]),
            "name": str(item.get("name") or item["id"]),
            "free": free,
            "context": int(item.get("context_length") or 0),
        })
    # Free models first, then alphabetical: an operator with a small budget can pick in one screen.
    rows.sort(key=lambda row: (not row["free"], row["id"]))
    return int(response.status_code), rows


def list_ai_models(*, api_key: str, base_url: str) -> AIModelsResult:
    """Return the models the gateway offers, so the UI can pick a working one.

    OpenRouter publishes ``/models`` without a token; other OpenAI-compatible
    gateways may require it. A missing token is not an error here — the request
    simply goes out unauthenticated and the gateway decides.
    """
    token = str(api_key or "").strip()
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return AIModelsResult(False, "missing_base_url", message="Укажите адрес API")
    try:
        status, rows = _model_catalogue(base, token)
    except Exception as exc:  # network/DNS/TLS/timeouts
        return AIModelsResult(False, f"unreachable:{type(exc).__name__}",
                              message="Сервер AI недоступен. Проверьте адрес API и сеть.")
    if status in {401, 403}:
        return AIModelsResult(False, f"http_{status}", http_status=status,
                              message="Токен отклонён сервером — список моделей недоступен. Проверьте ключ.")
    if status >= 400:
        return AIModelsResult(False, f"http_{status}", http_status=status,
                              message=f"Сервер ответил HTTP {status}. Проверьте адрес API.")
    if not rows:
        return AIModelsResult(False, "empty_catalogue", http_status=status,
                              message="Сервер не вернул список моделей. Имя модели можно ввести вручную.")
    free = sum(1 for row in rows if row["free"])
    message = f"Доступно моделей: {len(rows)}"
    message += f", из них бесплатных: {free}." if free else "."
    return AIModelsResult(True, None, http_status=status, models=rows, message=message)


def openrouter_healthcheck(*, base_url: str | None = None) -> tuple[bool, str | None]:
    cfg = get_ai_settings()
    if not cfg.enabled:
        return False, "disabled"
    if not cfg.api_key:
        return False, "missing_token"
    base = (str(base_url).strip() if base_url is not None else "") or cfg.base_url
    if not base:
        return False, "missing_base_url"
    result = probe_ai_connection(api_key=cfg.api_key, base_url=base, model=cfg.model)
    return bool(result.ok), result.reason
