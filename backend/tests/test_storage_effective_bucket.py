"""Хранилище, настроенное в интерфейсе, должно использоваться везде.

Администратор может сохранить бакет S3 в настройках. Если часть путей (проверка
готовности, предподписанная загрузка, импорт ZIP, уборка файлов) продолжает
читать `S3_BUCKET` из `.env`, платформа начинает работать с двумя разными
бакетами: загрузка уходит в один, импорт ищет файл в другом.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def ui_bucket(client, admin_headers):
    response = client.put("/admin/settings/storage", headers=admin_headers, json={
        "s3_endpoint_url": "https://s3.example.test",
        "s3_bucket": "ui-configured-bucket",
        "s3_region_name": "ru-central1",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    settings_payload = body.get("settings", body)
    assert settings_payload["effective"]["bucket"] == "ui-configured-bucket"
    return "ui-configured-bucket"


def test_health_ready_checks_the_bucket_from_settings(client, ui_bucket, storage):
    from app.core.config import settings
    assert settings.s3_bucket != ui_bucket
    response = client.get("/health/ready")
    assert response.status_code == 200, response.text
    assert storage.buckets and set(storage.buckets) == {ui_bucket}


def test_presigned_upload_targets_the_bucket_from_settings(ui_bucket, storage, monkeypatch):
    from app.services import storage as storage_service

    monkeypatch.setattr(storage_service, "_get_presign_client", lambda: storage)
    url = storage_service.presign_put(object_key="uploads/sources/module.zip", content_type=None)
    assert url.endswith("/module.zip")
    assert storage.buckets == [ui_bucket]


def test_storage_cors_and_scan_use_the_bucket_from_settings(client, admin_headers, ui_bucket, storage):
    cors = client.get("/admin/storage/bucket-cors", headers=admin_headers)
    assert cors.status_code in {200, 409, 502}, cors.text
    if cors.status_code == 200:
        assert set(storage.buckets) == {ui_bucket}

    storage.buckets.clear()
    listing = client.get("/admin/storage/objects", headers=admin_headers, params={"prefix": "modules/"})
    assert listing.status_code == 200, listing.text
    assert storage.buckets and set(storage.buckets) == {ui_bucket}


def test_import_job_reads_and_writes_the_bucket_from_settings(db, make_module, ui_bucket, storage):
    """Воркер скачивает ZIP и кладёт файлы урока туда же, куда пишет интерфейс."""
    import io
    import uuid as uuidlib
    import zipfile

    from app.services.module_import_jobs import import_module_zip_job

    module, _lesson, _quiz = make_module(required=False, title="Импорт в бакет из настроек II")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("01. Введение.txt", "Теория".encode())
    source = f"uploads/sources/test/{uuidlib.uuid4().hex}.zip"
    storage.objects[source] = buffer.getvalue()

    result = import_module_zip_job(s3_object_key=source, module_id=str(module.id),
                                   expected_revision=module.content_revision, reimport_existing=True)
    assert result["ok"], result
    assert storage.buckets, "воркер не обратился к S3"
    assert set(storage.buckets) == {ui_bucket}
