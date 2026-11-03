"""Multipart-загрузка импорта не должна работать с произвольным ключом в бакете.

Эти эндпоинты принимают `object_key` от клиента и ходят с ним в S3 напрямую.
Без проверки админ мог завершить или прервать загрузку по любому ключу —
например, перезаписать файл материала или объект библиотеки продаж.
Импорт всегда пишет в `uploads/sources/.../<имя>.zip`, поэтому разрешён
только этот префикс.
"""

import pytest


def _create_payload(**overrides):
    body = {"filename": "module.zip", "content_type": "application/zip", "size_bytes": 1024}
    body.update(overrides)
    return body


@pytest.mark.parametrize("endpoint", [
    "/admin/modules/multipart-import-presign-part",
    "/admin/modules/multipart-import-list-parts",
    "/admin/modules/multipart-import-complete",
    "/admin/modules/multipart-import-abort",
])
def test_multipart_import_rejects_foreign_object_keys(client, admin_headers, endpoint):
    response = client.post(endpoint, headers=admin_headers, json={
        "object_key": "modules/00000000-0000-0000-0000-000000000000/_versions/secret.pdf",
        "upload_id": "upload-1",
        "part_number": 1,
        "parts": [{"part_number": 1, "etag": "x"}],
    })
    assert response.status_code == 422, response.text
    assert "uploads/sources" in response.json()["error_message"]


def test_multipart_import_rejects_path_escapes(client, admin_headers):
    for key in ("uploads/sources/../../etc/secret.zip",
                "uploads/sources/a/b.zip//x",
                "uploads/other/file.zip",
                "uploads/sources/a/file.tar"):
        response = client.post("/admin/modules/multipart-import-abort", headers=admin_headers,
                               json={"object_key": key, "upload_id": "upload-1"})
        assert response.status_code == 422, (key, response.text)


def test_multipart_import_still_accepts_its_own_prefix(client, admin_headers, monkeypatch):
    import app.routers.admin as admin_module

    called = {}

    def fake_abort(*, object_key, upload_id):
        called["key"] = object_key

    monkeypatch.setattr(admin_module, "multipart_abort", fake_abort)
    response = client.post("/admin/modules/multipart-import-abort", headers=admin_headers, json={
        "object_key": "uploads/sources/deadbeef/module.zip", "upload_id": "upload-1",
    })
    assert response.status_code == 200, response.text
    assert called["key"] == "uploads/sources/deadbeef/module.zip"


def test_multipart_import_requires_admin(client, auth_headers):
    response = client.post("/admin/modules/multipart-import-abort", headers=auth_headers, json={
        "object_key": "uploads/sources/deadbeef/module.zip", "upload_id": "upload-1",
    })
    assert response.status_code == 403


@pytest.mark.parametrize("endpoint", [
    "/admin/modules/enqueue-import-zip",
    "/admin/modules/abort-import-zip",
])
def test_import_endpoints_reject_non_upload_keys(client, admin_headers, endpoint):
    for key in (
        "modules/00000000-0000-0000-0000-000000000000/_versions/secret.zip",
        "sales/photos/catalog.zip",
        "uploads/../secret.zip",
        "uploads/sources/a.zip//b",
        "uploads/notes.txt",
        "",
    ):
        response = client.post(endpoint, headers=admin_headers, json={"object_key": key})
        assert response.status_code in (400, 422), (key, response.text)


def test_abort_import_zip_keeps_the_source_archive(client, admin_headers, monkeypatch):
    """Отмена загрузки не удаляет исходный ZIP: он нужен для повторного импорта."""
    import app.routers.admin as admin_module

    deleted = []
    monkeypatch.setattr(admin_module, "ensure_bucket_exists", lambda: None, raising=False)
    monkeypatch.setattr(admin_module, "get_s3_client", lambda: type("S3", (), {
        "delete_object": lambda self, **kwargs: deleted.append(kwargs.get("Key")),
    })(), raising=False)

    response = client.post("/admin/modules/abort-import-zip", headers=admin_headers,
                           json={"object_key": "uploads/sources/deadbeef/module.zip", "filename": "module.zip"})
    assert response.status_code == 200, response.text
    assert deleted == []


def test_link_asset_validates_both_sides(client, admin_headers, make_module):
    """Связь «урок — файл» проверяется до вставки, а не падает 500 по FK."""
    import uuid

    _, lesson, _ = make_module()

    missing = client.post("/admin/submodules/link-asset", headers=admin_headers,
                          json={"submodule_id": str(uuid.uuid4()), "asset_id": str(uuid.uuid4()), "order": 1})
    assert missing.status_code == 404, missing.text
    assert "Урок" in missing.json()["error_message"]

    unknown_asset = client.post("/admin/submodules/link-asset", headers=admin_headers,
                                json={"submodule_id": str(lesson.id), "asset_id": str(uuid.uuid4()), "order": 1})
    assert unknown_asset.status_code == 404, unknown_asset.text
    assert "Файл" in unknown_asset.json()["error_message"]


def test_queue_outage_is_reported_as_503_not_500(client, admin_headers, monkeypatch):
    """Redis недоступен — админ видит «очередь недоступна», а не 500 без причины."""
    import app.routers.admin as admin_module

    def broken(*args, **kwargs):
        raise RuntimeError("Connection refused")

    monkeypatch.setattr(admin_module, "get_queue", broken)
    response = client.post("/admin/modules/storage-prefix/backfill", headers=admin_headers)
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["error_code"] == "queue_unavailable"
    assert "Redis" in body["error_message"]
