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
