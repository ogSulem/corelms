"""Предел размера ZIP-архива модуля действует на всех входах.

Архив — не «материал»: его скачивает и распаковывает воркер, поэтому у него
отдельный потолок `IMPORT_ZIP_MAX_ARCHIVE_BYTES`. Раньше он был только у
повторного импорта (жёстко 1 ГБ), а прямой путь импорта через предподписанную
загрузку не проверял размер вовсе — сервер узнавал о гигабайтах уже после
скачивания в воркере.
"""

from __future__ import annotations

import io
import os
import uuid
import zipfile

import pytest
from botocore.exceptions import ClientError


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


@pytest.fixture()
def small_archive_cap(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "import_zip_max_archive_bytes", 1024)
    yield 1024


def test_presigned_import_rejects_declared_oversize(client, admin_headers, small_archive_cap):
    response = client.post("/admin/modules/presign-import-zip", headers=admin_headers,
                           json={"filename": "module.zip", "title": "Слишком большой архив",
                                 "size_bytes": small_archive_cap + 1})
    assert response.status_code == 413, response.text
    message = str(response.json().get("detail") or response.json().get("error_message") or "").lower()
    assert "предел" in message or "больше" in message


def test_multipart_import_rejects_declared_oversize(client, admin_headers, small_archive_cap):
    response = client.post("/admin/modules/multipart-import-create", headers=admin_headers,
                           json={"filename": "module.zip", "size_bytes": small_archive_cap * 4})
    assert response.status_code == 413, response.text


def test_presigned_import_accepts_size_within_limit(client, admin_headers, small_archive_cap, storage, monkeypatch):
    from app.routers import admin as admin_router

    monkeypatch.setattr(admin_router, "presign_put",
                        lambda *, object_key, content_type, expires_seconds=None: f"https://storage.test/{object_key}")
    response = client.post("/admin/modules/presign-import-zip", headers=admin_headers,
                           json={"filename": "module.zip", "title": "Архив в пределе",
                                 "size_bytes": small_archive_cap - 1})
    assert response.status_code == 200, response.text
    assert response.json()["object_key"].startswith("uploads/sources/")


def test_reimport_rejects_archive_over_limit(client, admin_headers, make_module, small_archive_cap, storage):
    module, _lesson, _quiz = make_module()
    # Данные не сжимаются: предел считается по размеру самого ZIP-файла.
    payload = _zip_bytes({"01. Урок.txt": os.urandom(small_archive_cap + 100)})
    response = client.post(f"/admin/content/modules/{module.id}/reimport", headers=admin_headers,
                           data={"revision": module.content_revision},
                           files={"file": ("module.zip", payload)})
    assert response.status_code == 413, response.text


def test_worker_fails_before_downloading_an_oversized_archive(db, small_archive_cap, storage, monkeypatch):
    from app.services import module_import_jobs as jobs

    source = f"uploads/sources/test/{uuid.uuid4().hex}.zip"
    storage.objects[source] = _zip_bytes({"01. Урок.txt": os.urandom(small_archive_cap * 2)})
    ranged_reads: list[str | None] = []
    original = storage.get_object

    def tracked(*, Bucket, Key, Range=None):
        ranged_reads.append(Range)
        return original(Bucket=Bucket, Key=Key, Range=Range)

    monkeypatch.setattr(storage, "get_object", tracked)
    monkeypatch.setattr(jobs, "effective_bucket", lambda: "bucket")

    with pytest.raises(Exception) as error:
        jobs.import_module_zip_job(s3_object_key=source, module_id=None, expected_revision=None,
                                   reimport_existing=False)
    assert "too large" in str(error.value)
    # Единственное обращение к объекту — проверка существования на 1 байт.
    assert ranged_reads and all(value == "bytes=0-0" for value in ranged_reads)


def test_worker_error_code_survives_the_generic_wrapper(monkeypatch):
    """Обёртка задачи видит то же исключение второй раз и не должна затирать код."""
    from app.services import module_import_jobs as jobs

    class FakeJob:
        id = "job-preserve"
        meta: dict = {}

        def save_meta(self):
            return None

    job = FakeJob()
    monkeypatch.setattr(jobs, "get_current_job", lambda: job)
    monkeypatch.setattr(jobs, "_publish_admin_jobs_changed_throttled", lambda **kwargs: None)
    monkeypatch.setattr(jobs, "_persist_job_snapshot", lambda **kwargs: None)

    error = ValueError("zip archive too large: 999999 > 1024")
    jobs._set_job_error(error=error, error_code="IMPORT_SOURCE_ZIP_TOO_LARGE",
                        error_hint="ZIP-архив больше предела 1 КБ. Задаётся IMPORT_ZIP_MAX_ARCHIVE_BYTES.")
    jobs._set_job_error(error=error)  # как это делает обёртка import_module_zip_job

    assert job.meta["error_code"] == "IMPORT_SOURCE_ZIP_TOO_LARGE"
    assert "IMPORT_ZIP_MAX_ARCHIVE_BYTES" in job.meta["error_hint"]
    assert job.meta["error_message"].startswith("zip archive too large")


def test_worker_classifies_plain_failures_as_import_failed(monkeypatch):
    from app.services import module_import_jobs as jobs

    class FakeJob:
        id = "job-generic"
        meta: dict = {}

        def save_meta(self):
            return None

    job = FakeJob()
    monkeypatch.setattr(jobs, "get_current_job", lambda: job)
    monkeypatch.setattr(jobs, "_publish_admin_jobs_changed_throttled", lambda **kwargs: None)
    monkeypatch.setattr(jobs, "_persist_job_snapshot", lambda **kwargs: None)
    jobs._set_job_error(error=RuntimeError("unexpected"))
    assert job.meta["error_code"] == "IMPORT_FAILED"
