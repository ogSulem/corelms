import json
import uuid

from sqlalchemy import select

from app.models.asset import ContentAsset
from app.models.audit import LearningEvent, LearningEventType
from app.models.submodule_asset import SubmoduleAssetMap


def attach(db, module, lesson, storage, *, name="Инструкция.pdf", content=b"%PDF-1.7 abcdefghijk"):
    asset = ContentAsset(module_id=module.id, bucket="testing",
                         object_key=f"modules/{module.id}/_versions/{uuid.uuid4().hex}.pdf",
                         original_filename=name, mime_type="application/pdf")
    db.add(asset)
    db.flush()
    if lesson:
        db.add(SubmoduleAssetMap(submodule_id=lesson.id, asset_id=asset.id, order=1))
    db.commit()
    storage.objects[asset.object_key] = content
    return asset


def test_asset_view_event_does_not_store_storage_key(client, db, make_module, make_user, storage):
    """Ключ объекта в хранилище — внутренняя деталь: в журнал он больше не пишется."""
    module, lesson, _ = make_module()
    learner, headers = make_user()
    asset = attach(db, module, lesson, storage)

    assert client.get(f"/assets/{asset.id}/stream", headers=headers).status_code == 200
    assert client.get(f"/assets/{asset.id}/download", headers=headers).status_code == 200

    events = db.scalars(select(LearningEvent).where(LearningEvent.user_id == learner.id)).all()
    asset_events = [e for e in events if e.type == LearningEventType.asset_viewed]
    assert asset_events, "просмотр файла обязан попадать в журнал"
    for event in asset_events:
        meta = json.loads(event.meta)
        assert "object_key" not in meta
        assert asset.object_key not in (event.meta or "")


def test_recent_activity_hides_legacy_storage_key_and_fingerprint(client, db, make_module, make_user, storage, admin_headers):
    """Старые строки меты (платформа работает полгода) чистятся на чтении."""
    module, lesson, _ = make_module()
    learner, headers = make_user()
    asset = attach(db, module, lesson, storage)
    legacy_meta = json.dumps({
        "action": "view",
        "filename": asset.original_filename,
        "object_key": asset.object_key,
        "device_hash": "fp-secret",
        "token": "leaked-token",
        "mime_type": "application/pdf",
    }, ensure_ascii=False)
    db.add(LearningEvent(user_id=learner.id, type=LearningEventType.asset_viewed,
                         ref_id=asset.id, meta=legacy_meta))
    db.commit()

    for path in (f"/me/recent-activity", "/me/history"):
        response = client.get(path, headers=headers)
        assert response.status_code == 200, (path, response.text)
        assert "object_key" not in response.text, path
        assert asset.object_key not in response.text, path
        assert "fp-secret" not in response.text, path
        assert "leaked-token" not in response.text, path
        # Полезное поле остаётся: журнал должен читаться.
        assert asset.original_filename in response.text, path

    # Админка того же пользователя — те же правила.
    admin_history = client.get(f"/admin/users/{learner.id}/history", headers=admin_headers)
    assert admin_history.status_code == 200, admin_history.text
    assert "object_key" not in admin_history.text
    assert asset.object_key not in admin_history.text
    assert "fp-secret" not in admin_history.text


def test_plain_learning_meta_is_returned_as_before(client, db, make_module, make_user):
    """«read»/«module_open» — не JSON, но интерфейс их различает: не ломаем."""
    module, lesson, _ = make_module()
    learner, headers = make_user()
    db.add(LearningEvent(user_id=learner.id, type=LearningEventType.submodule_opened,
                         ref_id=lesson.id, meta="read"))
    db.commit()

    body = client.get("/me/recent-activity", headers=headers)
    assert body.status_code == 200, body.text
    assert any(item.get("meta") == "read" for item in body.json()["events"])

    history = client.get("/me/history", headers=headers)
    assert history.status_code == 200
    assert any(item.get("meta") == "read" for item in history.json()["items"])
