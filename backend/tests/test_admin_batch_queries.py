"""Диагностические экраны не должны делать запрос на каждую запись.

`thumbs/backfill` раньше спрашивал превью отдельно для каждого файла (до 5000
запросов), а `storage-scan` — уроки отдельно для каждого модуля (до 400). Оба
эндпоинта вызываются кнопкой в админке, то есть держат рабочий поток и пул
соединений. Тест считает реальные SQL-запросы через событие драйвера: рост
объёма данных не должен давать рост числа запросов.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event

from app.db import session as session_module
from app.models.asset import ContentAsset
from app.models.media import AssetThumb
from app.models.module import Module



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


def _asset(db, module: Module, name: str, key: str) -> ContentAsset:
    asset = ContentAsset(module_id=module.id, bucket="testing", object_key=key, original_filename=name,
                         mime_type="image/jpeg", size_bytes=1024, version=1)
    db.add(asset)
    db.flush()
    return asset


def test_thumbs_backfill_queries_do_not_scale_with_asset_count(client, admin_headers, db, make_module,
                                                               storage, query_counter, monkeypatch):
    enqueued: list[uuid.UUID] = []
    import app.services.thumbs as thumbs_service
    monkeypatch.setattr(thumbs_service, "enqueue_thumb", lambda asset_id: enqueued.append(asset_id))

    module, _, _ = make_module()
    for index in range(12):
        asset = _asset(db, module, f"photo-{index}.jpg", f"modules/{module.id}/photo-{index}.jpg")
        if index < 3:
            db.add(AssetThumb(asset_id=asset.id, source_version=asset.version, source_bucket=asset.bucket,
                              source_object_key=asset.object_key, state="ready", object_key="thumbs/x.jpg"))
    db.commit()

    query_counter.clear()
    response = client.post("/admin/maintenance/thumbs/backfill?limit=50", headers=admin_headers)
    assert response.status_code == 202, response.text
    # Один запрос на список файлов + один на их превью + аудит/коммит.
    # Старый код делал 1 + 12 запросов (по одному на файл); теперь их 4.
    assert len(query_counter) <= 8, query_counter
    assert len(enqueued) == 9


def test_storage_scan_does_not_query_lessons_per_module(client, admin_headers, db, make_module, storage,
                                                       query_counter):
    from app.models.module import Submodule

    from app.models.quiz import Quiz, QuizType

    for _ in range(8):
        module, _, _ = make_module()
        for index in range(3):
            # У каждого урока свой тест: quiz_id уникален.
            quiz = Quiz(type=QuizType.submodule, pass_threshold=70, attempts_limit=3)
            db.add(quiz)
            db.flush()
            db.add(Submodule(module_id=module.id, title=f"Урок {index}", order=index + 2, content="текст",
                             requires_quiz=True, quiz_id=quiz.id))
    db.commit()

    query_counter.clear()
    response = client.get("/admin/maintenance/modules/storage-scan?limit=10&sample_keys=5", headers=admin_headers)
    assert response.status_code == 200, response.text
    # Список модулей + один запрос на все уроки, а не по запросу на модуль.
    # Старый код: 1 + число модулей. Теперь два запроса независимо от объёма.
    assert len(query_counter) <= 6, query_counter
