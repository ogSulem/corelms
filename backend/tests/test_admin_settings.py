import io
import json
import uuid
from sqlalchemy import select

from app.core.config import settings
from app.core.secrets import decrypt_secret
from app.models.app_setting import AppSetting
from app.models.user import UserRole
from app.services.app_settings import get_ai_settings, get_sales_settings


TOKEN = "fake-token-aaaaaaaa"


def _save_ai(client, headers, **overrides):
    body = {"enabled": True, "api_key": TOKEN, "model": "openai/gpt-4o-mini",
            "base_url": "https://openrouter.ai/api/v1", **overrides}
    return client.put("/admin/settings/ai", headers=headers, json=body)


def test_ai_token_is_encrypted_masked_and_applied_without_restart(client, db, admin_headers, make_module):
    saved = _save_ai(client, admin_headers)
    assert saved.status_code == 200, saved.text
    payload = saved.json()["settings"]
    assert payload["configured"] is True and payload["api_key_present"] is True
    assert TOKEN not in json.dumps(payload)
    assert payload["api_key_masked"].endswith(TOKEN[-4:])

    row = db.scalar(select(AppSetting).where(AppSetting.key == "ai"))
    assert row is not None and row.updated_by is not None
    stored = json.loads(row.value)
    assert TOKEN not in row.value and stored["api_key"].startswith("enc:v1:")
    assert decrypt_secret(stored["api_key"]) == TOKEN

    module, _, _ = make_module()
    workspace = client.get(f"/admin/content/modules/{module.id}", headers=admin_headers)
    assert workspace.status_code == 200
    assert workspace.json()["capabilities"]["ai_configured"] is True
    assert workspace.json()["capabilities"]["ai_enabled"] is True


def test_ai_settings_keep_and_clear_an_existing_token(client, db, admin_headers):
    assert _save_ai(client, admin_headers).status_code == 200
    kept = _save_ai(client, admin_headers, api_key=None)
    assert kept.status_code == 200 and kept.json()["settings"]["configured"] is True
    cleared = _save_ai(client, admin_headers, api_key=None, clear_api_key=True)
    assert cleared.status_code == 200
    assert cleared.json()["settings"]["api_key_present"] is False
    # The server has no environment token in tests, so nothing is configured.
    assert cleared.json()["settings"]["configured"] is False
    assert get_ai_settings(db).api_key == ""


def test_ai_settings_reject_unsafe_addresses_and_are_admin_only(client, make_user):
    _, employee = make_user()
    assert client.get("/admin/settings/ai", headers=employee).status_code == 403
    assert client.put("/admin/settings/ai", headers=employee, json={"enabled": True}).status_code == 403
    for base in ("javascript:alert(1)", "ftp://example.com", "https://user:pass@example.com"):
        response = _save_ai(client, employee, base_url=base)
        assert response.status_code == 403
    admin = make_user(UserRole.admin)[1]
    assert _save_ai(client, admin, base_url="javascript:alert(1)").status_code == 422
    assert _save_ai(client, admin, api_key="has a space").status_code == 422


def test_saved_token_works_in_production_and_is_used_for_generation(client, admin_headers, monkeypatch):
    assert _save_ai(client, admin_headers, base_url="https://ai.example.test/v1").status_code == 200
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "allow_runtime_llm_overrides", False)
    monkeypatch.setattr(settings, "openrouter_enabled", False)
    monkeypatch.setattr(settings, "openrouter_api_key", None)

    from app.services import openrouter

    captured = {}

    class Response:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"questions": [{
                "type": "single", "prompt": "Что верно?\nA) Первое\nB) Второе\nC) Третье\nD) Четвёртое",
                "correct_answer": "B", "explanation": "Так в тексте."}]})}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None, headers=None):
            captured.update(url=url, headers=headers, payload=json)
            return Response()

    monkeypatch.setattr(openrouter.httpx, "Client", FakeClient)
    debug = {}
    questions = openrouter.generate_quiz_questions_openrouter(
        title="Урок", text="Подробный учебный текст про продажи и процессы.", n_questions=1, debug_out=debug)
    assert len(questions) == 1 and questions[0].correct_answer == "B", debug
    assert captured["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert captured["url"] == "https://ai.example.test/v1/chat/completions"
    assert captured["payload"]["model"] == "openai/gpt-4o-mini"


def test_batch_preparation_accepts_a_token_saved_in_the_ui(db, admin_headers, make_module, monkeypatch, client):
    import fakeredis
    import rq
    from app.services import quiz_drafts

    module, _, _ = make_module()
    assert _save_ai(client, admin_headers).status_code == 200
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "allow_runtime_llm_overrides", False)
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    raw = fakeredis.FakeRedis()
    monkeypatch.setattr(quiz_drafts, "get_queue", lambda _name: rq.Queue("settings-test", connection=raw))
    monkeypatch.setattr(quiz_drafts, "get_redis", lambda: raw)
    receipt = quiz_drafts.prepare_module_drafts(db, module, actor_id=uuid.uuid4(), count=3, only_missing=False)
    assert len(receipt["items"]) == 1 and receipt["items"][0]["job_id"]


def test_ai_connection_test_does_not_expose_the_token(client, admin_headers, monkeypatch):
    from app.services import openrouter_health

    calls = []

    class Response:
        status_code = 200

        def json(self):
            return {"data": [{"id": "openai/gpt-4o-mini"}, {"id": "openai/gpt-4.1-mini"}]}

    monkeypatch.setattr(openrouter_health.httpx, "get",
                        lambda url, headers=None, timeout=None: calls.append((url, headers)) or Response())
    result = client.post("/admin/settings/ai/test", headers=admin_headers,
                         json={"api_key": TOKEN, "base_url": "https://openrouter.ai/api/v1",
                               "model": "openai/gpt-4o-mini"})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["ok"] is True and body["model_available"] is True
    assert TOKEN not in result.text
    assert calls[0][0].endswith("/key") and calls[1][0].endswith("/models")


def test_sales_settings_are_superadmin_only_and_store_the_key_encrypted(client, db, make_user):
    admin = make_user(UserRole.admin)[1]
    superadmin = make_user(UserRole.superadmin)[1]
    body = {"spreadsheet_id": "sheet-id-example-aaaa", "api_key": "fake-google-key-aaaa",
            "service_account_json": None}
    assert client.put("/admin/settings/sales", headers=admin, json=body).status_code == 403
    saved = client.put("/admin/settings/sales", headers=superadmin, json=body)
    assert saved.status_code == 200, saved.text
    payload = saved.json()["settings"]
    assert payload["spreadsheet_id"] == body["spreadsheet_id"] and payload["api_key_present"]
    assert "fake-google-key-aaaa" not in saved.text
    row = db.scalar(select(AppSetting).where(AppSetting.key == "sales"))
    assert "fake-google-key-aaaa" not in row.value
    config = get_sales_settings(db)
    assert config.api_key == "fake-google-key-aaaa"
    assert payload["spreadsheet_url"].endswith("/edit")


def test_sales_service_account_json_is_validated(client, make_user):
    superadmin = make_user(UserRole.superadmin)[1]
    bad = client.put("/admin/settings/sales", headers=superadmin,
                     json={"spreadsheet_id": "abc", "service_account_json": "{broken"})
    assert bad.status_code == 422
    valid = client.put("/admin/settings/sales", headers=superadmin, json={
        "spreadsheet_id": "abc",
        "service_account_json": json.dumps({"client_email": "bot@example.test", "private_key": "fake-private-key-aaaa"}),
    })
    assert valid.status_code == 200, valid.text
    assert valid.json()["settings"]["service_account_email"] == "bot@example.test"


def test_sales_settings_test_endpoint_reports_sheet_titles(client, make_user, monkeypatch):
    from app.routers import settings as settings_router
    superadmin = make_user(UserRole.superadmin)[1]
    monkeypatch.setattr(settings_router, "list_sheet_titles", lambda **kwargs: ["Фото", "Каталоги"])
    result = client.post("/admin/settings/sales/test", headers=superadmin, json={
        "spreadsheet_id": "abc", "api_key": "key"})
    assert result.status_code == 200 and result.json()["ok"] is True
    assert result.json()["sheets"] == ["Фото", "Каталоги"]


def test_sales_links_feed_uses_the_saved_table_and_credentials(db, client, make_user, monkeypatch):
    from app.services import sales_links
    superadmin = make_user(UserRole.superadmin)[1]
    assert client.put("/admin/settings/sales", headers=superadmin,
                      json={"spreadsheet_id": "saved-table", "api_key": "saved-key"}).status_code == 200
    monkeypatch.setattr(sales_links, "read_sales_snapshot", lambda **kwargs: {
        "sheets": [("Ссылки", [["name", "link"], ["Прайс", "https://example.test/price.pdf"]])],
        "truncated": False,
    })
    payload = sales_links.get_sales_links_payload(bypass_cache=True)
    assert payload["status"] == "fresh"
    assert payload["blocks"][0]["links"][0]["url"] == "https://example.test/price.pdf"
    assert sales_links.source_url().endswith("/saved-table/edit")


def test_overview_reports_schema_target_and_server_limits(client, admin_headers):
    response = client.get("/admin/settings/overview", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    from app.routers.settings import expected_schema_revision
    assert body["schema"]["expected"] == expected_schema_revision()
    assert expected_schema_revision() == "0024"
    assert body["upload_max_bytes"] > 0


def test_reset_returns_to_server_defaults(client, db, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "env-token")
    monkeypatch.setattr(settings, "openrouter_enabled", True)
    assert _save_ai(client, admin_headers).status_code == 200
    reset = client.delete("/admin/settings/ai", headers=admin_headers)
    assert reset.status_code == 200
    payload = reset.json()["settings"]
    assert payload["api_key_source"] == "environment"
    assert payload["api_key_masked"].endswith("oken")


def test_a_token_saved_with_a_previous_key_is_reported_and_can_be_replaced(client, admin_headers, monkeypatch):
    assert _save_ai(client, admin_headers).status_code == 200
    monkeypatch.setattr(settings, "settings_encryption_key", "rotated-settings-key")
    current = client.get("/admin/settings/ai", headers=admin_headers)
    assert current.status_code == 200
    assert current.json()["token_error"] is True
    assert current.json()["configured"] is False
    replaced = _save_ai(client, admin_headers, api_key="fake-token-bbbbbbbb")
    assert replaced.status_code == 200
    assert replaced.json()["settings"]["token_error"] is False
    assert replaced.json()["settings"]["configured"] is True


def test_ai_connection_test_reports_a_rejected_key(client, admin_headers, monkeypatch):
    from app.services import openrouter_health

    class Response:
        status_code = 401

        def json(self):
            return {"error": {"message": "invalid api key"}}

    monkeypatch.setattr(openrouter_health.httpx, "get", lambda *args, **kwargs: Response())
    result = client.post("/admin/settings/ai/test", headers=admin_headers,
                         json={"api_key": "fake-bad-key-aaaa", "base_url": "https://openrouter.ai/api/v1"})
    assert result.status_code == 200
    assert result.json()["ok"] is False and result.json()["http_status"] == 401
    assert "отклонил" in result.json()["message"]


def test_a_draft_job_uses_the_token_saved_in_the_ui(client, db, admin_headers, make_module, monkeypatch):
    from app.services import openrouter
    from app.services.authoring import generate_quiz_draft_job, source_revision

    module, lesson, _ = make_module(content=(
        "Менеджер начинает разговор с уточнения задачи клиента. Затем он проверяет бюджет, "
        "сроки и критерии выбора. Предложение готовится только после согласования этих параметров. "
        "В конце встречи стороны фиксируют следующий шаг и ответственного за него."
    ))
    assert _save_ai(client, admin_headers, base_url="https://ai.example.test/v1").status_code == 200
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "allow_runtime_llm_overrides", False)
    monkeypatch.setattr(settings, "openrouter_api_key", None)

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"questions": [{
                "type": "single",
                "prompt": "Что менеджер уточняет в начале разговора?\nA) Задачу клиента\nB) Цвет визитки\nC) Погоду\nD) Ничего",
                "correct_answer": "A", "explanation": "Задача клиента определяет предложение."}]})}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(openrouter.httpx, "Client", FakeClient)
    result = generate_quiz_draft_job(str(module.id), str(lesson.id), module.content_revision, 1,
                                     source_fingerprint=source_revision(db, lesson))
    assert result["ok"] is True, result
    assert result["needs_review"] is True and len(result["questions"]) == 1
    assert result["source_label"] == "Конспект / текст урока"


def test_a_token_row_without_an_enabled_flag_is_treated_as_enabled(client, db, admin_headers):
    from app.core.secrets import encrypt_secret

    db.add(AppSetting(key="ai", value=json.dumps({"api_key": encrypt_secret(TOKEN)})))
    db.commit()
    config = get_ai_settings(db)
    assert config.enabled is True and config.configured is True
    assert config.sources["enabled"] == "database"


def test_storage_settings_are_saved_encrypted_and_masked(client, db, admin_headers):
    saved = client.put("/admin/settings/storage", headers=admin_headers,
                       json={"s3_endpoint_url": "https://s3.example.test", "s3_bucket": "bucket-test",
                             "s3_access_key_id": "fake-access-aaaaaaaa", "s3_secret_access_key": "fake-secret-bbbbbbbb"})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["ok"] is True and body["restart_required"] is False
    payload = body["settings"]
    assert payload["stored"] is True and payload["configured"] is True
    assert payload["fields"]["s3_bucket"] == "bucket-test"
    assert payload["resolved"]["bucket"] == "bucket-test"
    assert payload["resolved"]["endpoint_url"] == "https://s3.example.test"
    assert "fake-access-aaaaaaaa" not in json.dumps(payload) and "fake-secret-bbbbbbbb" not in json.dumps(payload)
    assert payload["access_key_masked"].startswith("fak") and "aaaaaaaa" not in payload["access_key_masked"]
    assert payload["sources"]["s3_bucket"] == "database"

    # Credentials live in the encrypted settings table, never in plaintext.
    row = db.scalar(select(AppSetting).where(AppSetting.key == "storage"))
    assert row is not None and row.updated_by is not None
    stored = json.loads(row.value)
    assert "fake-secret-bbbbbbbb" not in row.value
    assert stored["s3_secret_access_key"].startswith("enc:v1:")
    assert decrypt_secret(stored["s3_secret_access_key"]) == "fake-secret-bbbbbbbb"

    # The saved values are the effective ones immediately, without a restart.
    from app.services.storage import effective_bucket, effective_endpoint
    assert effective_bucket() == "bucket-test"
    assert effective_endpoint() == "https://s3.example.test"

    # A bucket is mandatory: an accidental empty save must not wipe storage.
    assert client.put("/admin/settings/storage", headers=admin_headers, json={"s3_bucket": ""}).status_code == 422
    assert effective_bucket() == "bucket-test"

    reset = client.delete("/admin/settings/storage", headers=admin_headers)
    assert reset.status_code == 200 and reset.json()["settings"]["stored"] is False
    assert db.scalar(select(AppSetting).where(AppSetting.key == "storage")) is None
    assert effective_bucket() == settings.s3_bucket


def test_storage_settings_stay_editable_in_production(client, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.delenv("ALLOW_RUNTIME_S3_OVERRIDES", raising=False)
    read = client.get("/admin/settings/storage", headers=admin_headers)
    assert read.status_code == 200 and read.json()["editable"] is True
    saved = client.put("/admin/settings/storage", headers=admin_headers, json={"s3_bucket": "other"})
    assert saved.status_code == 200 and saved.json()["settings"]["resolved"]["bucket"] == "other"


def test_storage_settings_are_admin_only(client, make_user):
    _, employee = make_user()
    assert client.get("/admin/settings/storage", headers=employee).status_code == 403
    assert client.put("/admin/settings/storage", headers=employee, json={"s3_bucket": "x"}).status_code == 403
    assert client.delete("/admin/settings/storage", headers=employee).status_code == 403


def test_storage_connection_test_reports_bucket_state(client, admin_headers, monkeypatch):
    from app.services import storage

    class Client:
        def head_bucket(self, **kwargs):
            if kwargs.get("Bucket") != "bucket-ok":
                raise RuntimeError("NoSuchBucket")

    monkeypatch.setattr(storage, "get_s3_client", lambda *a, **k: Client())
    monkeypatch.setattr(storage, "effective_bucket", lambda: "bucket-ok")
    ok = client.post("/admin/settings/storage/test", headers=admin_headers)
    assert ok.status_code == 200 and ok.json()["ok"] is True
    monkeypatch.setattr(storage, "effective_bucket", lambda: "bucket-missing")
    bad = client.post("/admin/settings/storage/test", headers=admin_headers)
    assert bad.status_code == 200 and bad.json()["ok"] is False
    assert "NoSuchBucket" in bad.json()["message"]


def test_platform_limits_are_editable_and_apply_immediately(client, db, admin_headers, make_module):
    saved = client.put("/admin/settings/platform", headers=admin_headers,
                       json={"upload_max_bytes": 5 * 1024 * 1024, "allow_public_register": True})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["restart_required"] is False
    payload = body["settings"]
    assert payload["upload_max_bytes"] == 5 * 1024 * 1024
    assert payload["allow_public_register"] is True
    assert payload["sources"]["upload_max_bytes"] == "database"
    assert payload["limits"]["min_upload_bytes"] == 1024 * 1024

    module, _, _ = make_module()
    capabilities = client.get(f"/admin/content/modules/{module.id}", headers=admin_headers).json()["capabilities"]
    assert capabilities["upload_max_bytes"] == 5 * 1024 * 1024

    row = db.scalar(select(AppSetting).where(AppSetting.key == "platform"))
    assert row is not None and row.updated_by is not None

    reset = client.delete("/admin/settings/platform", headers=admin_headers)
    assert reset.status_code == 200 and reset.json()["settings"]["stored"] is False
    assert reset.json()["settings"]["upload_max_bytes"] == settings.content_upload_max_bytes


def test_platform_limits_reject_out_of_range_values(client, admin_headers):
    for value in (0, 1024, 20 * 1024 * 1024 * 1024 + 1):
        response = client.put("/admin/settings/platform", headers=admin_headers,
                              json={"upload_max_bytes": value, "allow_public_register": False})
        assert response.status_code == 422, value


def test_platform_settings_are_admin_only(client, make_user):
    _, employee = make_user()
    assert client.get("/admin/settings/platform", headers=employee).status_code == 403
    assert client.put("/admin/settings/platform", headers=employee,
                      json={"upload_max_bytes": 1024 * 1024}).status_code == 403


def test_platform_upload_limit_is_enforced(client, admin_headers, make_module):
    module, _, _ = make_module()
    assert client.put("/admin/settings/platform", headers=admin_headers,
                      json={"upload_max_bytes": 1024 * 1024, "allow_public_register": False}).status_code == 200
    too_big = io.BytesIO(b"x" * (1024 * 1024 + 1024))
    response = client.post(f"/admin/content/modules/{module.id}/assets", headers=admin_headers,
                           data={"revision": "1"},
                           files={"file": ("big.bin", too_big, "application/octet-stream")})
    assert response.status_code == 413
    assert "1 МБ" in response.text


def test_public_registration_follows_the_saved_setting(client, admin_headers, monkeypatch):
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "allow_public_register", True)

    def register(name: str):
        return client.post("/auth/register", json={"name": name, "position": None, "role": "employee",
                                                   "password": "testpass123"})

    saved = client.put("/admin/settings/platform", headers=admin_headers,
                       json={"upload_max_bytes": 512 * 1024 * 1024, "allow_public_register": False})
    assert saved.status_code == 200
    closed = register(f"closed_{uuid.uuid4().hex[:8]}")
    assert closed.status_code == 403

    client.put("/admin/settings/platform", headers=admin_headers,
               json={"upload_max_bytes": 512 * 1024 * 1024, "allow_public_register": True})
    opened = register(f"open_{uuid.uuid4().hex[:8]}")
    assert opened.status_code in (200, 201), opened.text

    # «Сбросить к серверу» возвращает поведение из .env без перезапуска.
    client.delete("/admin/settings/platform", headers=admin_headers)
    assert register(f"back_{uuid.uuid4().hex[:8]}").status_code == 200
