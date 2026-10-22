import uuid

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.asset import AssetRevision, ContentAsset
from app.models.audit import LearningEvent
from app.models.completion import ModuleCompletion
from app.models.module import Module, Submodule
from app.models.submodule_asset import SubmoduleAssetMap


def workspace(client, headers, mid):
    response = client.get(f"/admin/content/modules/{mid}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def edit(client, headers, state, path="", **body):
    response = client.patch(f"/admin/content/modules/{state['module']['id']}{path}", headers=headers,
                            json={"revision": state["module"]["content_revision"], **body})
    assert response.status_code == 200, response.text
    return response.json()


def upload(client, headers, state, name="Таблица.csv", data=b"name;value\nfirst;10", **fields):
    response = client.post(f"/admin/content/modules/{state['module']['id']}/assets", headers=headers,
                           data={"revision": state["module"]["content_revision"], **fields},
                           files={"file": (name, data, "application/octet-stream")})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_draft_and_optimistic_conflicts(client, admin_headers):
    response = client.post("/admin/content/modules", headers=admin_headers, json={"title": "  Ручной модуль  "})
    assert response.status_code == 201, response.text
    initial = response.json()
    assert initial["module"]["title"] == "Ручной модуль"
    assert not initial["module"]["is_active"]
    mid = initial["module"]["id"]
    empty_publish = client.patch(f"/admin/content/modules/{mid}", headers=admin_headers,
                                 json={"revision": initial["module"]["content_revision"], "is_active": True})
    assert empty_publish.status_code == 409
    changed = edit(client, admin_headers, initial, description="Обновлённое описание")
    stale = client.patch(f"/admin/content/modules/{mid}", headers=admin_headers,
                         json={"revision": initial["module"]["content_revision"], "title": "Чужие изменения"})
    assert stale.status_code == 409
    assert workspace(client, admin_headers, mid) == changed


def test_new_lesson_preserves_earned_completion_but_is_not_read(client, admin_headers, make_module, make_user):
    module, lesson, _ = make_module(required=False)
    learner, headers = make_user()
    assert client.post(f"/submodules/{lesson.id}/read", headers=headers).status_code == 200
    old_progress = client.get(f"/progress/modules/{module.id}", headers=headers).json()
    assert old_progress["completed"] is True
    state = workspace(client, admin_headers, module.id)
    response = client.post(f"/admin/content/modules/{module.id}/lessons", headers=admin_headers,
                           json={"revision": state["module"]["content_revision"], "title": "Новый урок", "content": "Дополнение"})
    assert response.status_code == 201, response.text
    added = response.json()["lessons"][-1]
    progress = client.get(f"/progress/modules/{module.id}", headers=headers).json()
    assert progress["completed"] is True
    assert progress["current_completed"] is False
    assert progress["passed"] == 1 and progress["total"] == 2
    assert next(s for s in progress["submodules"] if s["submodule_id"] == added["id"])["read"] is False
    with SessionLocal() as db:
        achievement = db.get(ModuleCompletion, (learner.id, module.id))
        assert achievement and achievement.content_revision == old_progress["content_revision"]
    _, newcomer = make_user()
    fresh = client.get(f"/progress/modules/{module.id}", headers=newcomer).json()
    assert not fresh["completed"] and fresh["passed"] == 0


def test_reorder_does_not_move_read_identity(client, admin_headers, make_module, make_user):
    module, lesson, _ = make_module()
    _, headers = make_user()
    client.post(f"/submodules/{lesson.id}/read", headers=headers)
    state = workspace(client, admin_headers, module.id)
    for title in ["Второй", "Третий"]:
        response = client.post(f"/admin/content/modules/{module.id}/lessons", headers=admin_headers,
                               json={"revision": state["module"]["content_revision"], "title": title})
        assert response.status_code == 201
        state = response.json()
    ids = [s["id"] for s in reversed(state["lessons"])]
    response = client.put(f"/admin/content/modules/{module.id}/lesson-order", headers=admin_headers,
                          json={"revision": state["module"]["content_revision"], "ids": ids})
    assert response.status_code == 200, response.text
    assert [s["id"] for s in response.json()["lessons"]] == ids
    progress = client.get(f"/progress/modules/{module.id}", headers=headers).json()
    assert [s["submodule_id"] for s in progress["submodules"] if s["read"]] == [str(lesson.id)]
    bad = client.put(f"/admin/content/modules/{module.id}/lesson-order", headers=admin_headers,
                     json={"revision": response.json()["module"]["content_revision"], "ids": [ids[0], ids[0]]})
    assert bad.status_code == 422


def test_file_upload_replace_restore_move_archive(client, admin_headers, make_module, storage):
    module, lesson, _ = make_module()
    state = upload(client, admin_headers, workspace(client, admin_headers, module.id), submodule_id=str(lesson.id))
    asset = state["assets"][0]
    aid = asset["asset_id"]
    with SessionLocal() as db:
        original = db.get(ContentAsset, uuid.UUID(aid)).object_key
    state = upload(client, admin_headers, state, name="Другое название.csv", data=b"name;value\nsecond;20", replace_asset_id=aid)
    assert state["assets"][0]["asset_id"] == aid
    assert state["assets"][0]["original_filename"] == "Таблица.csv"
    assert state["assets"][0]["version"] == 2
    assert storage.objects[original] == b"name;value\nfirst;10"
    state = edit(client, admin_headers, state, f"/assets/{aid}", filename="Смета.csv", submodule_id=None)
    assert state["assets"][0]["submodule_id"] is None
    assert state["assets"][0]["original_filename"] == "Смета.csv"
    versions = client.get(f"/admin/content/modules/{module.id}/assets/{aid}/versions", headers=admin_headers).json()
    assert [v["version"] for v in versions["items"]] == [1]
    restored = client.post(f"/admin/content/modules/{module.id}/assets/{aid}/restore-version", headers=admin_headers,
                           json={"revision": state["module"]["content_revision"], "version": 1})
    assert restored.status_code == 200, restored.text
    state = restored.json()
    assert state["assets"][0]["version"] == 3
    assert state["assets"][0]["original_filename"] == "Смета.csv"
    with SessionLocal() as db:
        assert db.get(ContentAsset, uuid.UUID(aid)).object_key == original
        assert db.scalar(select(func.count()).select_from(AssetRevision).where(AssetRevision.asset_id == uuid.UUID(aid))) == 2
    state = edit(client, admin_headers, state, f"/assets/{aid}", is_archived=True)
    assert state["assets"][0]["is_archived"]
    state = edit(client, admin_headers, state, f"/assets/{aid}", is_archived=False)
    assert not state["assets"][0]["is_archived"]
    assert not storage.deleted


def test_duplicate_upload_and_wrong_module_asset_are_rejected(client, admin_headers, make_module, storage):
    module, _, _ = make_module()
    other, _, _ = make_module()
    state = upload(client, admin_headers, workspace(client, admin_headers, module.id))
    aid = state["assets"][0]["asset_id"]
    duplicate = client.post(f"/admin/content/modules/{module.id}/assets", headers=admin_headers,
                            data={"revision": state["module"]["content_revision"]}, files={"file": ("таблица.CSV", b"duplicate")})
    assert duplicate.status_code == 409
    alien = client.patch(f"/admin/content/modules/{other.id}/assets/{aid}", headers=admin_headers,
                                       json={"revision": other.content_revision, "is_archived": True})
    assert alien.status_code == 404
    assert len(storage.uploaded) == 1
    wrong_extension = client.patch(f"/admin/content/modules/{module.id}/assets/{aid}", headers=admin_headers,
                                   json={"revision": state["module"]["content_revision"], "filename": "Таблица.html"})
    assert wrong_extension.status_code == 422


def test_conflict_after_upload_only_removes_staged_bytes(client, admin_headers, make_module, storage, monkeypatch):
    from app.routers import content
    module, _, _ = make_module()
    state = upload(client, admin_headers, workspace(client, admin_headers, module.id))
    original_keys = set(storage.objects)
    def race(**kwargs):
        storage.upload(**kwargs)
        with SessionLocal() as other:
            row = other.get(Module, module.id)
            row.content_revision += 1
            row.description = "Другой редактор"
            other.commit()
    monkeypatch.setattr(content, "upload_fileobj_with_retry", race)
    response = client.post(f"/admin/content/modules/{module.id}/assets", headers=admin_headers,
                           data={"revision": state["module"]["content_revision"], "replace_asset_id": state["assets"][0]["asset_id"]},
                           files={"file": ("Таблица.csv", b"changed")})
    assert response.status_code == 409, response.text
    assert set(storage.objects) == original_keys
    assert not original_keys.intersection(storage.deleted)
    current = workspace(client, admin_headers, module.id)
    assert current["assets"][0]["version"] == 1
    assert current["module"]["description"] == "Другой редактор"


def test_module_archive_restore_never_deletes_history(client, admin_headers, make_module, make_user, storage):
    module, lesson, _ = make_module()
    learner, headers = make_user()
    client.post(f"/submodules/{lesson.id}/read", headers=headers)
    state = upload(client, admin_headers, workspace(client, admin_headers, module.id))
    asset_id = state["assets"][0]["asset_id"]
    # Old clients' DELETE is also an archive, not a destructive path.
    archived = client.delete(f"/admin/modules/{module.id}", headers=admin_headers)
    assert archived.status_code == 200, archived.text
    assert client.get(f"/modules/{module.id}", headers=headers).status_code == 404
    assert client.get(f"/assets/{asset_id}/preview", headers=headers).status_code == 404
    state = workspace(client, admin_headers, module.id)
    assert state["module"]["is_archived"] and len(state["assets"]) == 1
    state = edit(client, admin_headers, state, is_archived=False)
    assert not state["module"]["is_active"]
    state = edit(client, admin_headers, state, is_active=True)
    assert client.get(f"/progress/modules/{module.id}", headers=headers).json()["completed"]
    with SessionLocal() as db:
        assert db.get(ModuleCompletion, (learner.id, module.id))
        assert db.scalar(select(func.count()).select_from(LearningEvent).where(LearningEvent.user_id == learner.id)) > 0
    assert not storage.deleted


def test_file_order_with_multiple_archived_rows(client, admin_headers, make_module, storage):
    module, lesson, _ = make_module(folder=True)
    state = workspace(client, admin_headers, module.id)
    for name in ["1.csv", "2.csv", "3.csv", "4.csv"]:
        state = upload(client, admin_headers, state, name=name, submodule_id=str(lesson.id))
    ids = [a["asset_id"] for a in state["assets"]]
    archived = client.post(f"/admin/content/modules/{module.id}/assets/archive", headers=admin_headers,
                           json={"revision": state["module"]["content_revision"], "ids": ids[:2], "is_archived": True})
    assert archived.status_code == 200
    result = client.put(f"/admin/content/modules/{module.id}/asset-order", headers=admin_headers,
                        json={"revision": archived.json()["module"]["content_revision"], "submodule_id": str(lesson.id), "ids": list(reversed(ids[2:]))})
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        links = list(db.scalars(select(SubmoduleAssetMap).where(SubmoduleAssetMap.submodule_id == lesson.id)))
        assert len({link.order for link in links}) == 4


def test_employee_cannot_mutate_content(client, make_module, make_user):
    module, _, _ = make_module()
    _, headers = make_user()
    for method, path, kwargs in [("get", "", {}), ("patch", f"/{module.id}", {"json": {"revision": 1, "title": "Attack"}}),
                                ("post", "", {"json": {"title": "Attack"}})]:
        response = getattr(client, method)(f"/admin/content/modules{path}", headers=headers, **kwargs)
        assert response.status_code == 403


def test_summary_preserves_earned_progress_and_reports_current_coverage(client, admin_headers, db, make_module, make_user):
    # Exclude the baseline fixture's unrelated module for a transparent 1-course result.
    for item in db.scalars(select(Module)):
        item.is_active = False
    db.commit()
    module, lesson, _ = make_module(required=False)
    _, headers = make_user()
    client.post(f"/submodules/{lesson.id}/read", headers=headers)
    before = client.get("/me/progress-summary", headers=headers).json()
    assert before["percent"] == before["current_percent"] == 100
    state = workspace(client, admin_headers, module.id)
    client.post(f"/admin/content/modules/{module.id}/lessons", headers=admin_headers,
                json={"revision": state["module"]["content_revision"], "title": "Дополнение"})
    after = client.get("/me/progress-summary", headers=headers).json()
    assert after["modules_completed"] == 1 and after["percent"] == 100
    assert after["current_percent"] == 50 and after["steps_completed"] == 1
    recommended = client.get("/me/recommendations", headers=headers)
    assert recommended.status_code == 200 and str(module.id) not in recommended.json()["module_ids"]


def test_history_for_general_file_without_lesson(client, db, make_module, make_user):
    from app.models.audit import LearningEventType
    module, _, _ = make_module()
    user, headers = make_user()
    asset = ContentAsset(module_id=module.id, bucket="testing", object_key="history.csv", original_filename="Общий файл.csv")
    db.add(asset)
    db.flush()
    db.add(LearningEvent(user_id=user.id, type=LearningEventType.asset_viewed, ref_id=asset.id))
    db.commit()
    history = client.get("/me/history", headers=headers)
    assert history.status_code == 200, history.text
    event = next(item for item in history.json()["items"] if item["asset_id"] == str(asset.id))
    assert event["module_id"] == str(module.id) and event["module_title"] == module.title


def test_admin_reports_use_same_earned_completion_as_learner(client, admin_headers, make_module, make_user):
    module, lesson, _ = make_module(required=False)
    user, headers = make_user()
    client.post(f"/submodules/{lesson.id}/read", headers=headers)
    state = workspace(client, admin_headers, module.id)
    client.post(f"/admin/content/modules/{module.id}/lessons", headers=admin_headers,
                json={"revision": state["module"]["content_revision"], "title": "Новый шаг"})
    users = client.get("/admin/users", headers=admin_headers)
    assert users.status_code == 200, users.text
    row = next(item for item in users.json()["items"] if item["id"] == str(user.id))
    assert row["progress_summary"]["completed_count"] == 1
    detail = client.get(f"/admin/users/{user.id}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    completed = detail.json()["modules_progress"]["completed"]
    assert completed[0]["module_id"] == str(module.id) and completed[0]["percent"] == 100
    assert completed[0]["current_completed"] is False
    analytics = client.get(f"/admin/analytics/modules/{module.id}", headers=admin_headers)
    assert analytics.status_code == 200, analytics.text
    row = next(item for item in analytics.json()["rows"] if item["user_id"] == str(user.id))
    assert row["completed"] and row["passed_count"] == 1 and row["total_lessons"] == 2
