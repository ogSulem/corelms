import io
import stat
import uuid
import zipfile

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.asset import AssetRevision, ContentAsset
from app.models.module import Module, Submodule
from app.models.submodule_asset import SubmoduleAssetMap
from app.services.module_importer import import_module_from_dir
from app.services.module_import_jobs import _safe_extract_zip


def do_import(db, path, **kwargs):
    report = {}
    mid = import_module_from_dir(db=db, module_dir=path, title_override="Проверка импорта", generate_questions=False, report_out=report, **kwargs)
    db.commit()
    db.expire_all()
    return db.get(Module, mid), report


def test_merge_keeps_ids_progress_missing_paths_manual_names_and_quizzes(client, db, make_user, storage, tmp_path):
    root = tmp_path / "module"
    root.mkdir()
    (root / "01. Введение.txt").write_text("Первый учебный материал", encoding="utf-8")
    (root / "02. Инструкция.txt").write_text("Второй учебный материал", encoding="utf-8")
    module, _ = do_import(db, root)
    module.is_active = True
    db.commit()
    lessons = list(db.scalars(select(Submodule).where(Submodule.module_id == module.id).order_by(Submodule.order)))
    first, missing_later = lessons
    first_id, missing_id, quiz_id = first.id, missing_later.id, first.quiz_id
    first.title = "Ручное название урока"
    asset = db.scalar(select(ContentAsset).where(ContentAsset.source_path == "01. Введение.txt"))
    asset_id, original_key = asset.id, asset.object_key
    asset.original_filename = "Ручное название файла.txt"
    db.commit()
    _, headers = make_user()
    for lesson in lessons:
        assert client.post(f"/submodules/{lesson.id}/read", headers=headers).status_code == 200
    assert client.get(f"/progress/modules/{module.id}", headers=headers).json()["completed"]
    (root / "01. Введение.txt").write_text("Обновлённый первый материал", encoding="utf-8")
    (root / "02. Инструкция.txt").unlink()
    (root / "03. Дополнение.txt").write_text("Новый материал", encoding="utf-8")
    db.expire_all()
    updated, report = do_import(db, root, module_id_override=str(module.id), expected_revision=module.content_revision)
    assert updated.id == module.id and updated.is_active
    assert report["lessons_added"] == 1 and report["lessons_kept"] == 1
    assert report["files_updated"] == 1 and report["progress_preserved"]
    assert db.get(Submodule, first_id).title == "Ручное название урока"
    assert db.get(Submodule, first_id).quiz_id == quiz_id
    assert db.get(Submodule, missing_id) is not None
    current_asset = db.get(ContentAsset, asset_id)
    assert current_asset.original_filename == "Ручное название файла.txt"
    assert current_asset.version == 2
    assert storage.objects[original_key] == "Первый учебный материал".encode()
    assert db.scalar(select(func.count()).select_from(AssetRevision).where(AssetRevision.asset_id == asset_id)) == 1
    progress = client.get(f"/progress/modules/{module.id}", headers=headers).json()
    assert progress["completed"] and not progress["current_completed"]
    assert progress["total"] == 3 and progress["passed"] == 2
    assert not progress["submodules"][-1]["read"]
    # Identical re-import does not create another file version or upload bytes.
    uploads_before = len(storage.uploaded)
    _, repeated = do_import(db, root, module_id_override=str(module.id), expected_revision=updated.content_revision)
    assert repeated["files_updated"] == 0 and repeated["files_unchanged"] == 2
    assert len(storage.uploaded) == uploads_before


def test_file_move_archive_and_order_survive_reimport(db, storage, tmp_path):
    root = tmp_path / "module"
    (root / "Каталог").mkdir(parents=True)
    (root / "Каталог" / "Таблица.csv").write_text("a,b\n1,2")
    (root / "Урок.txt").write_text("Памятка")
    module, _ = do_import(db, root)
    folder = db.scalar(select(Submodule).where(Submodule.module_id == module.id, Submodule.is_folder.is_(True)))
    asset = db.scalar(select(ContentAsset).where(ContentAsset.source_path == "Каталог/Таблица.csv"))
    aid = asset.id
    link = db.scalar(select(SubmoduleAssetMap).where(SubmoduleAssetMap.asset_id == aid))
    db.delete(link)  # An administrator moved this file into general materials.
    asset.is_archived = True
    folder.title = "Переименованный каталог"
    folder.is_archived = True
    folder.order = 100
    db.commit()
    (root / "Каталог" / "Таблица.csv").write_text("a,b\n3,4")
    _, report = do_import(db, root, module_id_override=str(module.id))
    assert report["files_updated"] == 1 and report["files_added"] == 0
    assert db.get(ContentAsset, aid).is_archived
    assert db.scalar(select(SubmoduleAssetMap).where(SubmoduleAssetMap.asset_id == aid)) is None
    db.refresh(folder)
    assert folder.order == 100 and folder.title == "Переименованный каталог" and folder.is_archived


def test_ambiguous_legacy_lesson_is_not_matched_by_order(db, make_module, storage, tmp_path):
    from app.models.quiz import Quiz, QuizType
    module, lesson, _ = make_module(title="Проверка импорта")
    lesson.title = "Материал"
    second_quiz = Quiz(type=QuizType.submodule)
    db.add(second_quiz)
    db.flush()
    duplicate = Submodule(module_id=module.id, title="Материал", order=2, quiz_id=second_quiz.id, content="Другой материал", requires_quiz=False)
    db.add(duplicate)
    db.commit()
    root = tmp_path / "module"
    root.mkdir()
    (root / "Материал.txt").write_text("Переимпортированный текст")
    _, report = do_import(db, root, module_id_override=str(module.id))
    assert report["lessons_added"] == 1 and report["lessons_kept"] == 2
    assert report["warnings"]
    assert db.get(Submodule, duplicate.id).content == "Другой материал"
    assert db.get(Submodule, lesson.id).source_path is None


def test_import_conflict_cleans_only_its_new_objects(db, storage, tmp_path, monkeypatch):
    import app.services.module_importer as importer
    root = tmp_path / "module"
    root.mkdir()
    (root / "Файл.txt").write_text("Стабильная версия")
    module, _ = do_import(db, root)
    mid, revision = module.id, module.content_revision
    original_keys = set(storage.objects)
    (root / "Файл.txt").write_text("Новая версия")
    original_upload = importer._upload_file
    def concurrent_edit(**kwargs):
        result = original_upload(**kwargs)
        with SessionLocal() as other:
            m = other.get(Module, mid)
            m.content_revision += 1
            other.commit()
        return result
    monkeypatch.setattr(importer, "_upload_file", concurrent_edit)
    with pytest.raises(HTTPException) as error:
        do_import(db, root, module_id_override=str(mid), expected_revision=revision)
    assert error.value.status_code == 409
    assert set(storage.objects) == original_keys
    assert not original_keys.intersection(storage.deleted)
    assert db.scalar(select(ContentAsset.version).where(ContentAsset.module_id == mid)) == 1


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "C:/drive.txt", "a\\b.txt"])
def test_zip_path_traversal_rejected(tmp_path, name):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(name, "unsafe")
    stream.seek(0)
    with zipfile.ZipFile(stream) as archive, pytest.raises((ValueError, RuntimeError)):
        _safe_extract_zip(zf=archive, dest=tmp_path / "content")
    assert not (tmp_path / "escape.txt").exists()


def test_zip_symlinks_and_duplicate_entries_rejected(tmp_path):
    for symlink in [False, True]:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            if symlink:
                entry = zipfile.ZipInfo("link.txt")
                entry.create_system = 3
                entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(entry, "../outside")
            else:
                archive.writestr("a.txt", "first")
                with pytest.warns(UserWarning):
                    archive.writestr("a.txt", "second")
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive, pytest.raises((ValueError, RuntimeError)):
            _safe_extract_zip(zf=archive, dest=tmp_path / str(symlink))
