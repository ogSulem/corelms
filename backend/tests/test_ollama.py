import httpx

from app.core.config import settings
from app.services.ollama import generate_quiz_questions_ollama


class _Resp:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _ClientOk:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json):
        return _Resp(
            {
                "message": {
                    "content": '{"questions": [{"type": "single", "prompt": "Q?\\nA) a\\nB) b\\nC) c\\nD) d", "correct_answer": "A", "explanation": "because"}]}'
                },
                "done": True
            }
        )


class _ClientTimeout:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json):
        raise httpx.ReadTimeout("timed out")


class _ClientBadJson:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json):
        return _Resp({"message": {"content": "not-json"}})


def test_generate_quiz_questions_ollama_ok(monkeypatch):
    monkeypatch.setattr(settings, "ollama_enabled", True)
    monkeypatch.setattr(settings, "ollama_base_url", "http://ollama")
    monkeypatch.setattr(settings, "ollama_model", "dummy")

    import app.services.ollama as ollama_mod

    monkeypatch.setattr(ollama_mod.httpx, "Client", _ClientOk)

    out = generate_quiz_questions_ollama(title="T", text="X", n_questions=1)
    assert len(out) == 1
    assert out[0].correct_answer == "A"


def test_generate_quiz_questions_ollama_timeout_fallback(monkeypatch):
    monkeypatch.setattr(settings, "ollama_enabled", True)
    monkeypatch.setattr(settings, "ollama_base_url", "http://ollama")
    monkeypatch.setattr(settings, "ollama_model", "dummy")

    import app.services.ollama as ollama_mod

    monkeypatch.setattr(ollama_mod.httpx, "Client", _ClientTimeout)

    out = generate_quiz_questions_ollama(title="T", text="X", n_questions=1)
    assert out == []


def test_generate_quiz_questions_ollama_bad_json_fallback(monkeypatch):
    monkeypatch.setattr(settings, "ollama_enabled", True)
    monkeypatch.setattr(settings, "ollama_base_url", "http://ollama")
    monkeypatch.setattr(settings, "ollama_model", "dummy")

    import app.services.ollama as ollama_mod

    monkeypatch.setattr(ollama_mod.httpx, "Client", _ClientBadJson)

    out = generate_quiz_questions_ollama(title="T", text="X", n_questions=1)
    assert out == []
