"""Журнал серверных ошибок виден администратору и не течёт наружу."""

import json

import pytest

from app.services import error_log


@pytest.fixture()
def error_file(tmp_path, monkeypatch):
    path = tmp_path / "errors.jsonl"
    monkeypatch.setenv("CORELMS_ERROR_LOG_PATH", str(path))
    return path


def test_recent_errors_are_returned_newest_first(client, admin_headers, error_file):
    error_log.record(rid="rid-old", method="GET", path="/admin/users", status=500, exc=ValueError("boom"))
    error_log.record(rid="rid-new", method="POST", path="/modules/1/read", status=502, user_id="u1")

    response = client.get("/admin/diagnostics/errors", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert [item["rid"] for item in body["items"]] == ["rid-new", "rid-old"]
    oldest = body["items"][1]
    assert oldest["path"] == "/admin/users" and oldest["status"] == 500
    assert "ValueError: boom" in oldest["error"]
    assert "ValueError: boom" in oldest["traceback"]
    assert body["log_file"] == str(error_file)


def test_errors_can_be_looked_up_by_support_code(client, admin_headers, error_file):
    error_log.record(rid="rid-a", method="GET", path="/a", status=500)
    error_log.record(rid="rid-b", method="GET", path="/b", status=500)

    response = client.get("/admin/diagnostics/errors?request_id=rid-a", headers=admin_headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1 and items[0]["path"] == "/a"


def test_errors_journal_is_empty_and_honest_when_nothing_happened(client, admin_headers, error_file):
    response = client.get("/admin/diagnostics/errors", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == [] and body["count"] == 0
    assert body["hint"]


def test_errors_journal_is_admin_only(client, make_user, error_file):
    _, employee = make_user()
    assert client.get("/admin/diagnostics/errors", headers=employee).status_code == 403


def test_unhandled_exception_is_recorded_with_support_code(client, monkeypatch, error_file):
    from app.main import create_app

    app = create_app()

    @app.get("/__selfcheck_boom")
    def _boom():
        raise RuntimeError("контролируемое падение")

    from fastapi.testclient import TestClient

    local = TestClient(app, raise_server_exceptions=False)
    response = local.get("/__selfcheck_boom")
    assert response.status_code == 500
    rid = response.json()["request_id"]
    assert rid

    entries = [json.loads(line) for line in error_file.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["rid"] == rid
    assert entry["path"] == "/__selfcheck_boom"
    assert entry["status"] == 500
    assert "RuntimeError: контролируемое падение" in entry["error"]
    assert "_boom" in entry["traceback"] and "Traceback" in entry["traceback"]


def test_error_log_rotates_instead_of_growing_forever(tmp_path, monkeypatch):
    path = tmp_path / "errors.jsonl"
    monkeypatch.setenv("CORELMS_ERROR_LOG_PATH", str(path))
    monkeypatch.setattr(error_log, "MAX_BYTES", 2000)
    for index in range(40):
        error_log.record(rid=f"rid-{index}", method="GET", path="/x" * 5, status=500)

    assert path.exists()
    assert path.stat().st_size <= 2000 + 1024
    assert (tmp_path / "errors.jsonl.1").exists()


def _append_entry(path, *, ts: str, rid: str, status: int = 500):
    entry = {"ts": ts, "rid": rid, "method": "GET", "path": "/assets/x/stream", "status": status,
             "user_id": None, "duration_ms": 1200}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def test_old_errors_are_hidden_by_default_and_visible_on_request(client, admin_headers, error_file):
    """Разобранная ошибка месячной давности не должна выглядеть как текущая поломка."""
    from datetime import datetime, timedelta, timezone

    old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
    _append_entry(error_file, ts=old_ts, rid="rid-old")
    error_log.record(rid="rid-fresh", method="GET", path="/modules", status=500)

    body = client.get("/admin/diagnostics/errors", headers=admin_headers).json()
    assert [item["rid"] for item in body["items"]] == ["rid-fresh"]
    assert body["retention_days"] >= 1 and body["days"] == body["retention_days"]

    everything = client.get("/admin/diagnostics/errors?days=0", headers=admin_headers).json()
    assert [item["rid"] for item in everything["items"]] == ["rid-fresh", "rid-old"]
    assert everything["days"] == 0


def test_error_journal_can_be_cleared_and_does_not_pretend_to_have_old_entries(client, admin_headers, error_file):
    error_log.record(rid="rid-a", method="GET", path="/a", status=500, exc=ValueError("boom"))
    response = client.delete("/admin/diagnostics/errors", headers=admin_headers)

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert response.json()["cleared_bytes"] > 0
    assert not error_file.exists() or error_file.read_text(encoding="utf-8").strip() == ""

    body = client.get("/admin/diagnostics/errors?days=0", headers=admin_headers).json()
    assert body["items"] == [] and body["hint"]


def test_error_journal_clear_is_admin_only(client, make_user, error_file):
    _, employee = make_user()
    assert client.delete("/admin/diagnostics/errors", headers=employee).status_code == 403


def test_client_disconnect_is_not_recorded_as_server_error(client, monkeypatch, error_file):
    """Клиент закрыл видео — это не 500 в журнале (та самая ошибка из прода)."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.services.streaming import is_stream_interrupted

    from botocore.exceptions import IncompleteReadError, ResponseStreamingError

    assert error_file.parent.exists()
    interrupted = ResponseStreamingError(error=IncompleteReadError(actual_bytes=10, expected_bytes=20))
    assert is_stream_interrupted(interrupted) is True
    assert is_stream_interrupted(ExceptionGroup("tasks", [RuntimeError("x"), interrupted])) is True
    assert is_stream_interrupted(ValueError("boom")) is False

    app = create_app()

    @app.get("/__selfcheck_interrupted")
    def _interrupted():
        raise ResponseStreamingError(error=IncompleteReadError(actual_bytes=10, expected_bytes=20))

    local = TestClient(app, raise_server_exceptions=False)
    response = local.get("/__selfcheck_interrupted")
    assert response.status_code == 499
    assert not error_file.exists() or "ResponseStreamingError" not in error_file.read_text(encoding="utf-8")
