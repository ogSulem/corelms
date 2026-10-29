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
