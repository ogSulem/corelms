"""«Здоровье хранилища»: состояние превью считает база, а не память процесса.

Раньше эндпоинт выгружал весь каталог файлов и все строки превью, а страница
настроек запрашивает его автоматически при открытии. На каталоге в десятки
тысяч файлов это лишняя нагрузка на пул соединений и память. Тест фиксирует
и правильность цифр, и то, что число запросов не растёт с числом файлов.
"""
from __future__ import annotations

import pytest
from sqlalchemy import event

from app.db import session as session_module
from app.models.asset import ContentAsset
from app.models.media import AssetThumb


@pytest.fixture()
def query_counter():
    statements: list[str] = []

    def _listener(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    engine = session_module.engine
    event.listen(engine, "before_cursor_execute", _listener)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _listener)


def _asset(db, module, name, *, version=1, thumb_state=None):
    asset = ContentAsset(module_id=module.id, bucket="testing", object_key=f"modules/{module.id}/{name}",
                         original_filename=name, mime_type="application/octet-stream", size_bytes=1024,
                         version=version)
    db.add(asset)
    db.flush()
    if thumb_state is not None:
        db.add(AssetThumb(asset_id=asset.id, source_version=version, source_bucket=asset.bucket,
                          source_object_key=asset.object_key, state=thumb_state, object_key="thumbs/x.jpg",
                          size_bytes=2048))
        db.flush()
    return asset


def test_thumb_status_counts_and_ignores_non_previewable(client, admin_headers, db, make_module):
    module, _, _ = make_module()
    _asset(db, module, "ready.jpg", thumb_state="ready")
    _asset(db, module, "processing.MP4", thumb_state="processing")
    _asset(db, module, "broken.png", thumb_state="failed")
    _asset(db, module, "no-thumb.jpeg")
    _asset(db, module, "document.pdf")
    _asset(db, module, "archive.zip")
    db.commit()

    response = client.get("/admin/maintenance/thumbs/status", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["previewable"] == 4
    assert payload["states"] == {"ready": 1, "processing": 1, "failed": 1, "missing": 1}
    assert payload["thumb_bytes"] >= 3 * 2048
    names = {item["name"] for item in payload["items"]}
    assert names == {"ready.jpg", "processing.MP4", "broken.png", "no-thumb.jpeg"}
    assert {item["state"] for item in payload["items"]} == {"ready", "processing", "failed", "missing"}


def test_thumb_status_queries_do_not_grow_with_catalog(client, admin_headers, db, make_module, query_counter):
    module, _, _ = make_module()
    for index in range(40):
        _asset(db, module, f"photo-{index}.jpg", thumb_state="ready" if index % 2 else None)
    db.commit()

    query_counter.clear()
    response = client.get("/admin/maintenance/thumbs/status", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["previewable"] == 40
    # Три-четыре запроса независимо от числа файлов (раньше — два огромных IN).
    assert len(query_counter) <= 6, query_counter


def test_old_thumb_version_does_not_count_as_current(client, admin_headers, db, make_module):
    module, _, _ = make_module()
    asset = _asset(db, module, "replaced.jpg", version=1, thumb_state="ready")
    asset.version = 2
    db.add(asset)
    db.commit()

    payload = client.get("/admin/maintenance/thumbs/status", headers=admin_headers).json()
    assert payload["states"].get("missing") == 1
    assert payload["states"].get("ready") is None
