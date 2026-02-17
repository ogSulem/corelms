import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings
from app.services.openrouter_health import openrouter_healthcheck
from app.services.openrouter import generate_quiz_questions_openrouter

print("OPENROUTER_ENABLED =", settings.openrouter_enabled)
print("OPENROUTER_BASE_URL =", settings.openrouter_base_url)
print("OPENROUTER_MODEL =", settings.openrouter_model)
print("OPENROUTER_API_KEY set =", bool(os.environ.get("OPENROUTER_API_KEY")))
print("LLM_PROVIDER_ORDER =", settings.llm_provider_order)

ok, meta = openrouter_healthcheck()
print("healthcheck ok =", ok)
print("healthcheck meta =", meta)

debug = {}
qs = generate_quiz_questions_openrouter(
    title="Тестовый урок",
    text="Это короткий учебный текст про технику безопасности на производстве.",
    n_questions=3,
    debug_out=debug,
)
print("questions n =", len(qs))
print("debug =", debug)
if qs:
    print("sample:", qs[0].prompt[:200])
