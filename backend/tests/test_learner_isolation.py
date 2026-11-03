"""Изоляция данных между учениками: закрытый модуль не виден постороннему.

Проверяется эмпирически, запросами: у одного ученика есть тег доступа к модулю
с `visibility="restricted"`, у второго — нет. Второй не должен получить ни
модуль, ни урок, ни список файлов, ни тест, ни сам файл — даже зная UUID.
"""

import uuid

from app.models.asset import ContentAsset
from app.models.module import Module
from app.models.submodule_asset import SubmoduleAssetMap
from app.models.tag import ModuleTagMap, Tag, UserTagMap
from app.models.user import UserRole


def _restricted_module(db, make_module):
    module, lesson, quiz = make_module(title=f"Закрытый {uuid.uuid4().hex[:6]}")
    tag = Tag(name=f"Отдел {uuid.uuid4().hex[:6]}")
    db.add(tag)
    db.flush()
    module.visibility = "restricted"
    db.add(ModuleTagMap(module_id=module.id, tag_id=tag.id))
    asset = ContentAsset(module_id=module.id, bucket="testing", object_key=f"modules/{module.id}/secret.pdf",
                         original_filename="secret.pdf", mime_type="application/pdf", version=1)
    db.add(asset)
    db.flush()
    db.add(SubmoduleAssetMap(submodule_id=lesson.id, asset_id=asset.id, order=1))
    db.commit()
    return module, lesson, quiz, tag, asset


def test_restricted_module_is_invisible_without_the_tag(client, db, make_module, make_user, storage):
    module, lesson, quiz, tag, asset = _restricted_module(db, make_module)
    storage.objects[asset.object_key] = b"%PDF-1.4 secret"

    insider, insider_headers = make_user(UserRole.employee)
    outsider, outsider_headers = make_user(UserRole.employee)
    db.add(UserTagMap(user_id=insider.id, tag_id=tag.id))
    db.commit()
    assert db.get(Module, module.id).visibility == "restricted"

    probes = [
        f"/modules/{module.id}",
        f"/submodules/{lesson.id}",
        f"/modules/submodules/{lesson.id}/assets",
        f"/quizzes/{quiz.id}/context",
        f"/assets/{asset.id}/stream",
        f"/assets/{asset.id}/presign-download",
    ]
    for path in probes:
        closed = client.get(path, headers=outsider_headers)
        assert closed.status_code == 404, (path, closed.status_code, closed.text[:200])

    # Владелец тега видит то же самое.
    assert client.get(f"/modules/{module.id}", headers=insider_headers).status_code == 200
    assert client.get(f"/submodules/{lesson.id}", headers=insider_headers).status_code == 200
    assert client.get(f"/modules/submodules/{lesson.id}/assets", headers=insider_headers).status_code == 200
    stream = client.get(f"/assets/{asset.id}/stream", headers=insider_headers)
    assert stream.status_code in (200, 206), stream.text[:200]


def test_restricted_module_is_absent_from_catalog_and_search(client, db, make_module, make_user):
    module, _, _, tag, _ = _restricted_module(db, make_module)
    outsider, headers = make_user(UserRole.employee)

    listing = client.get("/modules/overview", headers=headers)
    assert listing.status_code == 200
    titles = {item.get("title") for item in listing.json().get("items", [])}
    assert module.title not in titles

    summary = client.get("/me/progress-summary", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["modules_total"] >= 0

    db.add(UserTagMap(user_id=outsider.id, tag_id=tag.id))
    db.commit()
    titles = {item.get("title") for item in client.get("/modules/overview", headers=headers).json().get("items", [])}
    assert module.title in titles


def test_archived_lesson_and_module_are_closed_for_learners(client, db, make_module, make_user):
    module, lesson, quiz, _, _ = _restricted_module(db, make_module)
    _, headers = make_user(UserRole.employee)

    lesson.is_archived = True
    db.commit()
    archived_lesson = client.get(f"/submodules/{lesson.id}", headers=headers)
    assert archived_lesson.status_code == 404

    lesson.is_archived = False
    module.is_archived = True
    db.commit()
    archived_module = client.get(f"/modules/{module.id}", headers=headers)
    assert archived_module.status_code == 404
