import hashlib

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.asset import ContentAsset
from app.models.lesson_revision import LessonRevision
from app.models.module import Submodule
from app.services.content import referenced_storage_keys
from test_content_lifecycle import edit, workspace
from test_import_preservation import do_import


def imported(db, tmp_path):
    root = tmp_path / "module"
    root.mkdir()
    (root / "Инструкция.txt").write_text("Исходный текст", encoding="utf-8")
    module, _ = do_import(db, root)
    lesson = db.scalar(select(Submodule).where(Submodule.module_id == module.id))
    return root, module, lesson


def test_manual_text_survives_changed_zip_and_can_be_restored(client, db, admin_headers, storage, tmp_path):
    root, module, lesson = imported(db, tmp_path)
    assert lesson.content_mode == "import" and lesson.content_version == 1
    initial = workspace(client, admin_headers, module.id)
    manual = edit(client, admin_headers, initial, f"/lessons/{lesson.id}", content="Редакторская инструкция")
    assert manual["lessons"][0]["content_mode"] == "manual"
    assert manual["lessons"][0]["content_version"] == 2
    (root / "Инструкция.txt").write_text("Новый текст из ZIP", encoding="utf-8")
    db.expire_all()
    module, report = do_import(db, root, module_id_override=str(module.id))
    assert report["files_updated"] == 1
    assert any("ручной текст сохранён" in warning for warning in report["warnings"])
    assert db.get(Submodule, lesson.id).content == "Редакторская инструкция"
    assert db.get(Submodule, lesson.id).content_version == 2
    base = f"/admin/content/modules/{module.id}/lessons/{lesson.id}"
    versions = client.get(base + "/versions", headers=admin_headers).json()
    assert [item["version"] for item in versions["items"]] == [1]
    assert client.get(base + "/versions/1", headers=admin_headers).json()["content"] == "Исходный текст"
    restored = client.post(base + "/restore-version", headers=admin_headers,
                          json={"version": 1, "revision": module.content_revision})
    assert restored.status_code == 200, restored.text
    current = restored.json()["lessons"][0]
    assert (current["content"], current["content_mode"], current["content_version"]) == ("Исходный текст", "manual", 3)
    assert client.get(base + "/versions/2", headers=admin_headers).json()["content"] == "Редакторская инструкция"


def test_import_mode_is_explicit_title_edits_do_not_disable_it(client, db, admin_headers, storage, tmp_path):
    root, module, lesson = imported(db, tmp_path)
    state = edit(client, admin_headers, workspace(client, admin_headers, module.id), f"/lessons/{lesson.id}", title="Новое название")
    assert state["lessons"][0]["content_mode"] == "import" and state["lessons"][0]["content_version"] == 1
    (root / "Инструкция.txt").write_text("Вторая версия", encoding="utf-8")
    db.expire_all()
    do_import(db, root, module_id_override=str(module.id))
    assert db.get(Submodule, lesson.id).content == "Вторая версия"
    assert db.get(Submodule, lesson.id).content_version == 2
    state = edit(client, admin_headers, workspace(client, admin_headers, module.id), f"/lessons/{lesson.id}", content="Ручная правка")
    state = edit(client, admin_headers, state, f"/lessons/{lesson.id}", content_mode="import")
    (root / "Инструкция.txt").write_text("Третья версия", encoding="utf-8")
    db.expire_all()
    do_import(db, root, module_id_override=str(module.id))
    assert db.get(Submodule, lesson.id).content == "Третья версия"
    assert db.scalar(select(func.count()).select_from(LessonRevision).where(LessonRevision.submodule_id == lesson.id)) == 4


def test_legacy_external_text_is_loaded_snapshotted_retained_and_restorable(client, db, admin_headers, make_module, storage):
    module, lesson, _ = make_module(content="")
    lesson.content_object_key = "legacy/lesson.txt"
    storage.objects[lesson.content_object_key] = "Старый текст из хранилища".encode()
    db.commit()
    base = f"/admin/content/modules/{module.id}/lessons/{lesson.id}"
    initial = workspace(client, admin_headers, module.id)
    assert initial["lessons"][0]["has_external_content"]
    assert client.get(base + "/content", headers=admin_headers).json()["content"] == "Старый текст из хранилища"
    renamed = edit(client, admin_headers, initial, f"/lessons/{lesson.id}", title="Другое название")
    db.expire_all()
    assert db.get(Submodule, lesson.id).content_object_key == "legacy/lesson.txt"
    cleared = edit(client, admin_headers, renamed, f"/lessons/{lesson.id}", content="")
    assert cleared["lessons"][0]["content_version"] == 2
    db.expire_all()
    assert "legacy/lesson.txt" in referenced_storage_keys(db)
    assert client.get(base + "/versions/1", headers=admin_headers).json()["content"] == "Старый текст из хранилища"
    result = client.post(base + "/restore-version", headers=admin_headers, json={"revision": cleared["module"]["content_revision"], "version": 1})
    assert result.status_code == 200 and result.json()["lessons"][0]["content"] == "Старый текст из хранилища"
    assert all(body.closed for body in storage.bodies)


def test_history_acl_missing_source_and_optimistic_conflict(client, db, admin_headers, make_user, make_module):
    module, lesson, _ = make_module()
    _, employee = make_user()
    base = f"/admin/content/modules/{module.id}/lessons/{lesson.id}"
    assert client.get(base + "/versions", headers=employee).status_code == 403
    assert client.patch(base, headers=admin_headers, json={"revision": module.content_revision, "content_mode": "import"}).status_code == 422
    changed = edit(client, admin_headers, workspace(client, admin_headers, module.id), f"/lessons/{lesson.id}", content="Изменено")
    assert client.post(base + "/restore-version", headers=admin_headers, json={"version": 1, "revision": changed["module"]["content_revision"] - 1}).status_code == 409
    other, _, _ = make_module()
    assert client.get(f"/admin/content/modules/{other.id}/lessons/{lesson.id}/versions/1", headers=admin_headers).status_code == 404


def test_import_preserves_original_video_and_manual_replacement(db, storage, tmp_path, monkeypatch):
    from app.services import module_importer
    root = tmp_path / "module"
    root.mkdir()
    (root / "Видео.mov").write_bytes(b"source video")
    calls = []
    def transcode(*, file_path, rel_name):
        calls.append(rel_name)
        out = tmp_path / "encoded.mp4"
        out.write_bytes(f"nondeterministic encoded bytes {len(calls)}".encode())
        return out, "Видео.mp4", "video/mp4"
    monkeypatch.setattr(module_importer, "_maybe_transcode_video", transcode)
    module, _ = do_import(db, root)
    asset = db.scalar(select(ContentAsset).where(ContentAsset.module_id == module.id))
    assert asset.source_checksum_sha256 == hashlib.sha256(b"source video").hexdigest()
    assert asset.source_checksum_sha256 == asset.checksum_sha256
    assert asset.original_filename == "Видео.mov"
    assert storage.objects[asset.object_key] == b"source video"
    assert calls == []
    # Simulate a separate editor replacement, whose source ZIP did not change.
    asset.object_key = "manual/version.mp4"
    asset.checksum_sha256 = hashlib.sha256(b"manual replacement").hexdigest()
    asset.version += 1
    db.commit()
    _, report = do_import(db, root, module_id_override=str(module.id))
    assert calls == [] and report["files_unchanged"] == 1
    assert db.get(ContentAsset, asset.id).object_key == "manual/version.mp4"
    assert db.get(ContentAsset, asset.id).version == 2


def test_zip_cannot_silently_claim_a_manually_uploaded_file(client, db, admin_headers, make_module, storage, tmp_path):
    from test_content_lifecycle import upload
    module, lesson, _ = make_module(title="Проверка импорта")
    lesson.title = "Урок"
    db.commit()
    initial = workspace(client, admin_headers, module.id)
    uploaded = upload(client, admin_headers, initial, name="Урок.txt", data=b"manual notes", submodule_id=str(lesson.id))
    original_key = db.scalar(select(ContentAsset).where(ContentAsset.module_id == module.id)).object_key
    root = tmp_path / "module"
    root.mkdir()
    (root / "Урок.txt").write_text("New ZIP text", encoding="utf-8")
    db.expire_all()
    with pytest.raises(ValueError, match="добавлен вручную"):
        do_import(db, root, module_id_override=str(module.id))
    assert storage.objects[original_key] == b"manual notes" and original_key not in storage.deleted
    db.expire_all()
    assert db.scalar(select(ContentAsset).where(ContentAsset.module_id == module.id)).version == 1
