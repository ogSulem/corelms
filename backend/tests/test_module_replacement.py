"""Замена модуля (переимпорт ZIP): прогресс, мусор и лишняя работа.

Вопрос, на который отвечает файл: если администратор обновляет существующий
модуль архивом, сохраняется ли пройденное обучение, не остаются ли в базе и в
хранилище бесхозные файлы, и не делается ли при этом работа, которая не нужна.
"""

import io
import uuid
import zipfile

import pytest
from sqlalchemy import func, select

from app.models.asset import AssetRevision, ContentAsset
from app.models.completion import ModuleCompletion
from app.models.media import AssetRendition, AssetThumb
from app.models.module import Module, Submodule
from app.models.quiz import Question, Quiz
from app.services.content import referenced_storage_keys
from app.services.module_import_jobs import import_module_zip_job


def zip_of(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def run_import(db, storage, module, files, *, revision=None):
    source = f"uploads/sources/test/{uuid.uuid4().hex}.zip"
    storage.objects[source] = zip_of(files)
    result = import_module_zip_job(s3_object_key=source, module_id=str(module.id),
                                   expected_revision=revision if revision is not None else module.content_revision,
                                   reimport_existing=True)
    assert result["ok"], result
    db.expire_all()
    return result


@pytest.fixture()
def imported(db, make_module, storage):
    """Модуль, собранный из ZIP: два урока и файл-инструкция."""
    module, _lesson, _quiz = make_module(required=False, title="Замена модуля")
    run_import(db, storage, module, {
        "01. Введение.txt": "Первый учебный материал".encode(),
        "02. Практика.txt": "Второй учебный материал".encode(),
        "02. Инструкция.pdf": b"%PDF-1.4 instruction",
    }, revision=module.content_revision)
    db.expire_all()
    module = db.get(Module, module.id)
    module.is_active = True
    db.commit()
    return module


def _lessons(db, module):
    return list(db.scalars(select(Submodule).where(Submodule.module_id == module.id).order_by(Submodule.order)))


def _read_all(client, headers, db, module):
    for lesson in _lessons(db, module):
        assert client.post(f"/submodules/{lesson.id}/read", headers=headers).status_code == 200


def test_replacing_module_keeps_progress_and_leaves_no_garbage(client, db, imported, storage, make_user):
    module = imported
    _learner, headers = make_user()
    _read_all(client, headers, db, module)
    before = client.get(f"/progress/modules/{module.id}", headers=headers).json()
    assert before["completed"] and before["current_completed"]
    lessons_before = {s.title: s.id for s in _lessons(db, module)}
    quiz_ids_before = {s.title: s.quiz_id for s in _lessons(db, module)}
    imported_assets = lambda: [a for a in db.scalars(select(ContentAsset).where(
        ContentAsset.module_id == module.id)) if a.source_path]
    assets_before = len(imported_assets())
    assert assets_before == 3

    # Новый архив: изменён текст первого урока, добавлен третий, файл-инструкция исчез.
    run_import(db, storage, module, {
        "01. Введение.txt": "Переработанный первый материал".encode(),
        "02. Практика.txt": "Второй учебный материал".encode(),
        "03. Дополнение.txt": "Совсем новый материал".encode(),
    })
    module = db.get(Module, module.id)
    lessons_after = {s.title: s for s in _lessons(db, module)}

    # Уроки сопоставлены по исходному пути: идентификаторы, тесты и прогресс целы.
    assert set(lessons_before).issubset(lessons_after)
    for title, lesson_id in lessons_before.items():
        assert lessons_after[title].id == lesson_id
        assert lessons_after[title].quiz_id == quiz_ids_before[title]
    assert db.scalar(select(func.count()).select_from(ModuleCompletion).where(
        ModuleCompletion.module_id == module.id)) == 1
    progress = client.get(f"/progress/modules/{module.id}", headers=headers).json()
    assert progress["completed"] is True, "замена модуля отозвала зачёт"
    assert progress["current_completed"] is False, "новый урок должен требовать прохождения"
    assert progress["has_updates"] is True, "ученику не сообщили об обновлении материалов"
    assert [s["read"] for s in progress["submodules"]][:2] == [True, True]

    # Старые файлы остались (исчезнувший из ZIP не удаляется), новый добавился,
    # дублей по исходному пути нет.
    assets = imported_assets()
    assert len(assets) == assets_before + 1  # «03. Дополнение.txt»
    assert len({asset.source_path for asset in assets}) == len(assets)
    assert any(asset.source_path == "02. Инструкция.pdf" for asset in assets)
    # Изменённый файл получил новую версию, прошлая осталась в истории.
    assert db.scalar(select(func.count()).select_from(AssetRevision).where(
        AssetRevision.asset_id.in_([asset.id for asset in assets]))) == 1

    # Мусора в хранилище нет: каждый объект модуля на кого-то ссылается.
    referenced = referenced_storage_keys(db)
    prefixes = {a.object_key.rsplit("/", 1)[0] + "/" for a in assets if a.object_key}
    assert prefixes, "импорт обязан положить файлы в хранилище"
    module_keys = [key for key in storage.objects if any(key.startswith(p) for p in prefixes)]
    assert module_keys, "импорт обязан положить файлы в хранилище"
    orphans = sorted(key for key in module_keys if key not in referenced)
    assert orphans == [], f"в хранилище остались бесхозные объекты: {orphans}"


def test_unchanged_reimport_does_no_media_work(db, imported, storage, monkeypatch):
    """Импорт без изменений не должен заново ставить в очередь перекодирование и превью."""
    from app.services import media, thumbs

    module = imported
    stages, thumbs_enqueued = [], []
    monkeypatch.setattr(media, "stage_rendition", lambda db, asset, **kwargs: stages.append(asset.id))
    monkeypatch.setattr(thumbs, "enqueue_thumb", lambda asset_id: thumbs_enqueued.append(asset_id))

    result = run_import(db, storage, module, {
        "01. Введение.txt": "Первый учебный материал".encode(),
        "02. Практика.txt": "Второй учебный материал".encode(),
        "02. Инструкция.pdf": b"%PDF-1.4 instruction",
    })
    assert result["report"]["files_unchanged"] == 3
    assert stages == [] and thumbs_enqueued == []


def test_reimport_cleans_derivatives_of_forgotten_versions(db, imported, storage):
    """Три замены видео: производные самой старой версии уходят из базы и из S3."""
    module = imported
    lesson = _lessons(db, module)[1]

    def add_video(version_payload: bytes):
        run_import(db, storage, module, {
            "01. Введение.txt": "Первый учебный материал".encode(),
            "02. Практика.txt": "Второй учебный материал".encode(),
            "02. Инструкция.pdf": b"%PDF-1.4 instruction",
            "02. Видео.mp4": version_payload,
        })
        db.expire_all()
        asset = db.scalar(select(ContentAsset).where(ContentAsset.module_id == module.id,
                                                    ContentAsset.source_path == "02. Видео.mp4"))
        assert asset is not None
        return asset

    asset = add_video(b"video one")
    keys = {}
    for version in (1, 2, 3):
        rendition_key = f"renditions/{asset.id}/{version}.mp4"
        thumb_key = f"thumbs/{asset.id}/{version}.jpg"
        storage.objects[rendition_key] = b"copy"
        storage.objects[thumb_key] = b"thumb"
        db.flush()
        # Импорт уже поставил рендишн в очередь — обновляем его, а не дублируем.
        rendition = db.scalar(select(AssetRendition).where(AssetRendition.asset_id == asset.id,
                                                          AssetRendition.source_version == version))
        if rendition is None:
            rendition = AssetRendition(asset_id=asset.id, source_version=version, source_bucket="testing",
                                       source_object_key=f"modules/original/{version}.mp4")
            db.add(rendition)
        rendition.bucket, rendition.object_key, rendition.state = "testing", rendition_key, "ready"
        thumb = db.scalar(select(AssetThumb).where(AssetThumb.asset_id == asset.id,
                                                  AssetThumb.source_version == version))
        if thumb is None:
            thumb = AssetThumb(asset_id=asset.id, source_version=version, source_bucket="testing",
                               source_object_key=f"modules/original/{version}.mp4")
            db.add(thumb)
        thumb.bucket, thumb.object_key, thumb.state = "testing", thumb_key, "ready"
        keys[version] = (rendition_key, thumb_key)
        db.commit()
        if version < 3:
            asset = add_video(f"video {version + 1}".encode())

    db.expire_all()
    assert db.get(ContentAsset, asset.id).version == 3
    # Четвёртый (без изменений) импорт запускает уборку производных.
    run_import(db, storage, module, {
        "01. Введение.txt": "Первый учебный материал".encode(),
        "02. Практика.txt": "Второй учебный материал".encode(),
        "02. Инструкция.pdf": b"%PDF-1.4 instruction",
        "02. Видео.mp4": b"video 3",
    })
    db.expire_all()

    kept_versions = {row.source_version for row in db.scalars(
        select(AssetRendition).where(AssetRendition.asset_id == asset.id))}
    assert kept_versions == {2, 3}, "остаться должны текущая и одна предыдущая версия"
    assert keys[1][0] not in storage.objects and keys[1][1] not in storage.objects
    assert keys[2][0] in storage.objects and keys[3][0] in storage.objects


def test_reimport_warns_when_updated_lesson_is_archived(db, imported, storage):
    """Урок в архиве обновится, но ученик этого не увидит — админ должен знать."""
    module = imported
    lesson = db.scalar(select(Submodule).where(Submodule.module_id == module.id,
                                               Submodule.source_path == "file:01. Введение.txt"))
    assert lesson is not None
    lesson.is_archived = True
    db.commit()

    result = run_import(db, storage, module, {
        "01. Введение.txt": "Изменённый текст архивного урока".encode(),
        "02. Практика.txt": "Второй учебный материал".encode(),
        "02. Инструкция.pdf": b"%PDF-1.4 instruction",
    })
    warnings = " ".join(result["report"].get("warnings") or [])
    assert "в архиве" in warnings, warnings
    db.expire_all()
    assert db.get(Submodule, lesson.id).is_archived, "импорт не должен молча восстановить урок"


def test_reimport_reports_files_that_left_the_archive(db, imported, storage):
    """Файл исчез из ZIP: он не удаляется, но админ обязан это увидеть."""
    module = imported
    result = run_import(db, storage, module, {
        "01. Введение.txt": "Первый учебный материал".encode(),
        "02. Практика.txt": "Второй учебный материал".encode(),
    })
    report = result["report"]
    assert report["files_missing"] == 1
    warnings = " ".join(report["warnings"])
    assert "Инструкция.pdf" in warnings
    db.expire_all()
    assert db.scalar(select(ContentAsset).where(ContentAsset.module_id == module.id,
                                               ContentAsset.source_path == "02. Инструкция.pdf")) is not None


def test_learner_closes_updates_after_finishing_new_lesson(client, db, imported, storage, make_user):
    """Метка «есть обновления» не залипает: прошёл новый урок — она снимается."""
    module = imported
    _learner, headers = make_user()
    _read_all(client, headers, db, module)
    assert client.post(f"/modules/{module.id}/open", headers=headers).status_code == 200

    run_import(db, storage, module, {
        "01. Введение.txt": "Переработанный первый материал".encode(),
        "02. Практика.txt": "Второй учебный материал".encode(),
        "02. Инструкция.pdf": b"%PDF-1.4 instruction",
        "04. Итоги.txt": "Четвёртый материал".encode(),
    })
    progress = client.get(f"/progress/modules/{module.id}", headers=headers).json()
    assert progress["completed"] is True and progress["current_completed"] is False
    assert progress["has_updates"] is True

    new_lesson = next(s for s in progress["submodules"]
                      if s["submodule_id"] and not s["read"])
    assert client.post(f"/submodules/{new_lesson['submodule_id']}/read", headers=headers).status_code == 200
    assert client.post(f"/modules/{module.id}/open", headers=headers).status_code == 200
    progress = client.get(f"/progress/modules/{module.id}", headers=headers).json()
    assert progress["current_completed"] is True and progress["completed"] is True
    assert progress["has_updates"] is False, "ученик всё прошёл, а метка обновлений осталась"


def test_importing_a_zip_with_existing_title_offers_replacing_it(client, db, imported, storage, admin_headers):
    """Дубль по названию — не тупик: сервер отдаёт код и id модуля для обновления."""
    module = imported
    object_key = "uploads/sources/test/Замена модуля.zip"
    storage.objects[object_key] = zip_of({"01. Введение.txt": b"text"})
    response = client.post("/admin/modules/enqueue-import-zip", headers=admin_headers, json={
        "object_key": object_key, "title": module.title, "source_filename": "Замена модуля.zip",
    })
    assert response.status_code == 409, response.text
    payload = response.json()
    assert payload["error_code"] == "module_already_exists"
    assert payload["module_id"] == str(module.id)
    assert module.title in payload["error_message"]
    assert db.scalar(select(func.count()).select_from(Module).where(Module.title == module.title)) == 1


def test_reimport_during_open_quiz_keeps_the_attempt_submittable(client, db, imported, storage, admin_headers, make_user):
    """Пока ученик проходит тест, импорт не должен обнулить его попытку."""
    module = imported
    lesson = db.scalar(select(Submodule).where(Submodule.module_id == module.id,
                                               Submodule.source_path == "file:02. Практика.txt"))
    quiz = db.get(Quiz, lesson.quiz_id)
    quiz.attempts_limit = 3
    db.add(Question(quiz_id=quiz.id, type="single", prompt="Вопрос\nA) Да\nB) Нет", correct_answer="A",
                    position=1, concept_tag="ok"))
    lesson.requires_quiz = True
    db.commit()

    _learner, headers = make_user()
    assert client.post(f"/submodules/{lesson.id}/read", headers=headers).status_code == 200
    started = client.post(f"/quizzes/{lesson.quiz_id}/start", headers=headers)
    assert started.status_code == 200, started.text
    attempt = started.json()

    # Импорт обновлённого архива прямо во время попытки.
    run_import(db, storage, module, {
        "01. Введение.txt": "Первый учебный материал".encode(),
        "02. Практика.txt": "Обновлённый второй материал".encode(),
        "02. Инструкция.pdf": b"%PDF-1.4 instruction",
    })

    submitted = client.post(f"/quizzes/{lesson.quiz_id}/submit", headers=headers, json={
        "session_id": attempt["session_id"],
        "answers": [{"question_id": q["id"], "answer": "A"} for q in attempt["questions"]],
    })
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["passed"] is True
