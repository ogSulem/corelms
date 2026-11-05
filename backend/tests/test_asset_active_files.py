"""Активные файлы (SVG/HTML/XML/JS) отдаются только как скачивание.

Если хранилище опубликовано с того же домена, что и приложение (обычный
вариант с обратным прокси), открытие SVG «в браузере» исполняло бы скрипт на
домене LMS. Поэтому такие файлы всегда уходят с `attachment` и нейтральным
типом, а видео и PDF по-прежнему открываются на месте.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.asset import ContentAsset
from app.models.module import Module


@pytest.fixture()
def patched_presign(monkeypatch):
    calls: list[dict] = []

    def fake_presign_get(**kwargs):
        calls.append(kwargs)
        return "https://storage.test/object"

    import app.routers.assets as assets_router

    monkeypatch.setattr(assets_router, "presign_get", fake_presign_get)
    return calls


def _asset(db, storage, *, name: str, mime: str, body: bytes = b"payload") -> ContentAsset:
    module = Module(title=f"Модуль {uuid.uuid4().hex[:6]}", is_active=True, visibility="public")
    db.add(module)
    db.flush()
    key = f"modules/{module.id}/files/{uuid.uuid4().hex}/{name}"
    storage.objects[key] = body
    asset = ContentAsset(module_id=module.id, bucket="bucket", object_key=key, original_filename=name,
                         mime_type=mime, size_bytes=len(body), version=1, is_archived=False, order=1)
    db.add(asset)
    db.commit()
    return asset


@pytest.mark.parametrize("name,mime", [
    ("схема.svg", "image/svg+xml"),
    ("страница.html", "text/html"),
    ("данные.xml", "application/xml"),
    ("script.js", "application/javascript"),
])
def test_active_content_is_forced_to_download(client, db, storage, make_user, patched_presign, name, mime):
    asset = _asset(db, storage, name=name, mime=mime)
    _user, headers = make_user()
    response = client.get(f"/assets/{asset.id}/presign-download?action=view", headers=headers)
    assert response.status_code == 200, response.text
    call = patched_presign[-1]
    assert call["response_content_disposition"].startswith("attachment"), call
    assert call["response_content_type"] == "application/octet-stream", call


def test_pdf_and_video_still_open_in_place(client, db, storage, make_user, patched_presign):
    pdf = _asset(db, storage, name="урок.pdf", mime="application/pdf", body=b"%PDF-1.4 test")
    _user, headers = make_user()
    assert client.get(f"/assets/{pdf.id}/presign-download?action=view", headers=headers).status_code == 200
    call = patched_presign[-1]
    assert call["response_content_disposition"].startswith("inline"), call
    assert call["response_content_type"] == "application/pdf"
