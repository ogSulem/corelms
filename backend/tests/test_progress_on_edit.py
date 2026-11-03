"""Прогресс ученика при правке модуля и уроков: что обязано сохраняться.

Вопрос, на который отвечает файл: если администратор меняет урок (текст,
название, порядок), заменяет файл, пересобирает тест или переимпортирует
модуль — не теряется ли зачёт ученика, не появляется ли мусор в базе и не
рисуется ли ложная метка «есть обновления».
"""

import uuid

from sqlalchemy import func, select

from app.models.asset import AssetRevision, ContentAsset
from app.models.attempt import QuizAttempt, QuizAttemptAnswer
from app.models.audit import LearningEvent
from app.models.completion import LessonQuizVersion, ModuleCompletion
from app.models.lesson_revision import LessonRevision
from app.models.module import Module, Submodule
from app.models.quiz import Question, Quiz
from app.models.submodule_asset import SubmoduleAssetMap
from app.models.user import User, UserRole


def _workspace(client, headers, mid):
    response = client.get(f"/admin/content/modules/{mid}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _patch(client, headers, state, path="", **body):
    response = client.patch(f"/admin/content/modules/{state['module']['id']}{path}", headers=headers,
                            json={"revision": state["module"]["content_revision"], **body})
    assert response.status_code == 200, response.text
    return response.json()


def _build_two_lesson_module(client, admin_headers, learner_headers):
    """Черновик → урок с текстом → урок с тестом → публикация."""
    created = client.post("/admin/content/modules", headers=admin_headers,
                          json={"title": f"Правки {uuid.uuid4().hex[:6]}"})
    assert created.status_code == 201, created.text
    state = created.json()

    first = client.post(f"/admin/content/modules/{state['module']['id']}/lessons", headers=admin_headers,
                        json={"revision": state["module"]["content_revision"], "title": "Урок 1",
                              "content": "Исходный текст первого урока"})
    assert first.status_code == 201, first.text
    state = first.json()

    second = client.post(f"/admin/content/modules/{state['module']['id']}/lessons", headers=admin_headers,
                         json={"revision": state["module"]["content_revision"], "title": "Урок 2",
                               "content": "Исходный текст второго урока"})
    assert second.status_code == 201, second.text
    state = second.json()
    lesson_two = [item for item in state["lessons"] if item["title"] == "Урок 2"][0]

    quiz = client.put(f"/admin/content/modules/{state['module']['id']}/lessons/{lesson_two['id']}/quiz",
                      headers=admin_headers, json={
                          "revision": state["module"]["content_revision"], "enabled": True, "pass_threshold": 70,
                          "attempts_limit": 3, "time_limit": None,
                          "questions": [{"type": "single", "stem": "Вопрос?", "options": ["Да", "Нет"],
                                         "correct": [0]}],
                      })
    assert quiz.status_code == 200, quiz.text
    state = quiz.json()["workspace"]

    published = _patch(client, admin_headers, state, is_active=True)
    return published


def _read_and_pass(client, headers, state):
    lesson_one = [s for s in state["lessons"] if s["title"] == "Урок 1"][0]
    lesson_two = [s for s in state["lessons"] if s["title"] == "Урок 2"][0]
    assert client.post(f"/submodules/{lesson_one['id']}/read", headers=headers).status_code == 200
    assert client.post(f"/submodules/{lesson_two['id']}/read", headers=headers).status_code == 200
    session = client.post(f"/quizzes/{lesson_two['quiz_id']}/start", headers=headers)
    assert session.status_code == 200, session.text
    attempt = session.json()
    submitted = client.post(f"/quizzes/{lesson_two['quiz_id']}/submit", headers=headers, json={
        "session_id": attempt["session_id"],
        "answers": [{"question_id": q["id"], "answer": "A"} for q in attempt["questions"]],
    })
    assert submitted.status_code == 200, submitted.text
    return lesson_one, lesson_two


def _progress(client, headers, mid):
    response = client.get(f"/progress/modules/{mid}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_editing_lesson_text_keeps_read_quiz_and_completion(client, db, admin_headers, make_user, storage):
    _, learner = make_user(UserRole.employee)
    state = _build_two_lesson_module(client, admin_headers, learner)
    module_id = state["module"]["id"]
    lesson_one, lesson_two = _read_and_pass(client, learner, state)
    before = _progress(client, learner, module_id)
    assert before["completed"] and before["current_completed"]

    edited = client.patch(f"/admin/content/modules/{module_id}/lessons/{lesson_one['id']}", headers=admin_headers,
                          json={"revision": state["module"]["content_revision"], "content": "Новый текст урока"})
    assert edited.status_code == 200, edited.text
    state = edited.json()
    assert [item for item in state["lessons"] if item["id"] == lesson_one["id"]][0]["content"] == "Новый текст урока"

    after = _progress(client, learner, module_id)
    assert after["completed"], "правка текста отозвала зачёт"
    assert after["current_completed"], "правка текста сбросила текущее прохождение"
    assert after["has_updates"], "о новом тексте ученику не сообщили"
    assert after["completed_at"] == before["completed_at"], "дата зачёта изменилась"
    assert [s["read"] for s in after["submodules"]] == [True, True]
    assert after["submodules"][1]["best_score"] == after["submodules"][1]["best_score"] == 100

    # История версий текста: одна запись на правку, без дублей.
    versions = list(db.scalars(select(LessonRevision).where(LessonRevision.submodule_id == uuid.UUID(lesson_one["id"]))))
    assert len(versions) == 1 and versions[0].content == "Исходный текст первого урока"

    # Повторное сохранение того же текста не плодит версии и «обновления».
    same = client.patch(f"/admin/content/modules/{module_id}/lessons/{lesson_one['id']}", headers=admin_headers,
                        json={"revision": state["module"]["content_revision"], "content": "Новый текст урока"})
    assert same.status_code == 200, same.text
    assert db.scalar(select(func.count()).select_from(LessonRevision).where(
        LessonRevision.submodule_id == uuid.UUID(lesson_one["id"]))) == 1

    # Открытие модуля снимает метку обновлений, зачёт остаётся.
    assert client.post(f"/modules/{module_id}/open", headers=learner).status_code == 200
    cleared = _progress(client, learner, module_id)
    assert not cleared["has_updates"] and cleared["completed"]


def test_renaming_lesson_does_not_claim_new_content(client, db, admin_headers, make_user):
    _, learner = make_user(UserRole.employee)
    state = _build_two_lesson_module(client, admin_headers, learner)
    module_id = state["module"]["id"]
    lesson_one, _ = _read_and_pass(client, learner, state)
    assert client.post(f"/modules/{module_id}/open", headers=learner).status_code == 200

    renamed = client.patch(f"/admin/content/modules/{module_id}/lessons/{lesson_one['id']}", headers=admin_headers,
                           json={"revision": state["module"]["content_revision"], "title": "Урок 1 (новое имя)",
                                 "presentation_mode": "text", "outline_path": "Раздел/Урок"})
    assert renamed.status_code == 200, renamed.text
    assert not _progress(client, learner, module_id)["has_updates"], "переименование выдало «есть обновления»"


def test_reorder_and_lesson_archive_keep_earned_completion(client, db, admin_headers, make_user):
    _, learner = make_user(UserRole.employee)
    state = _build_two_lesson_module(client, admin_headers, learner)
    module_id = state["module"]["id"]
    lesson_one, lesson_two = _read_and_pass(client, learner, state)

    reordered = client.put(f"/admin/content/modules/{module_id}/lesson-order", headers=admin_headers,
                           json={"revision": state["module"]["content_revision"],
                                 "ids": [lesson_two["id"], lesson_one["id"]]})
    assert reordered.status_code == 200, reordered.text
    state = reordered.json()
    after_reorder = _progress(client, learner, module_id)
    assert after_reorder["completed"] and after_reorder["current_completed"]
    assert {s["read"] for s in after_reorder["submodules"]} == {True}

    archived = client.patch(f"/admin/content/modules/{module_id}/lessons/{lesson_one['id']}", headers=admin_headers,
                            json={"revision": state["module"]["content_revision"], "is_archived": True})
    assert archived.status_code == 200, archived.text
    state = archived.json()
    after_archive = _progress(client, learner, module_id)
    assert after_archive["completed"], "архив урока отозвал зачёт модуля"
    assert len(after_archive["submodules"]) == 1

    restored = client.patch(f"/admin/content/modules/{module_id}/lessons/{lesson_one['id']}", headers=admin_headers,
                            json={"revision": state["module"]["content_revision"], "is_archived": False})
    assert restored.status_code == 200, restored.text
    after_restore = _progress(client, learner, module_id)
    assert after_restore["completed"] and after_restore["current_completed"]
    assert [s["read"] for s in after_restore["submodules"]] == [True, True]


def test_rebuilding_quiz_keeps_attempts_and_results(client, db, admin_headers, make_user):
    _, learner = make_user(UserRole.employee)
    state = _build_two_lesson_module(client, admin_headers, learner)
    module_id = state["module"]["id"]
    _, lesson_two = _read_and_pass(client, learner, state)
    attempts_before = db.scalar(select(func.count()).select_from(QuizAttempt))

    # Админ заменяет вопросы теста (новая версия теста, старые ответы остаются).
    rebuilt = client.put(f"/admin/content/modules/{module_id}/lessons/{lesson_two['id']}/quiz", headers=admin_headers,
                         json={"revision": state["module"]["content_revision"], "enabled": True, "pass_threshold": 70,
                               "attempts_limit": 3, "time_limit": None,
                               "questions": [{"type": "single", "stem": "Другой вопрос?", "options": ["Да", "Нет"],
                                              "correct": [0]}]})
    assert rebuilt.status_code == 200, rebuilt.text
    state = rebuilt.json()["workspace"]
    lesson_two_now = [s for s in state["lessons"] if s["title"] == "Урок 2"][0]
    assert lesson_two_now["quiz_id"] != lesson_two["quiz_id"], "вопросы заменили в том же тесте"

    # Старая попытка и её ответы на месте, зачёт по уроку сохранён.
    assert db.scalar(select(func.count()).select_from(QuizAttempt)) == attempts_before
    assert db.scalar(select(func.count()).select_from(QuizAttemptAnswer)) > 0
    progress = _progress(client, learner, module_id)
    assert progress["completed"] and progress["current_completed"]
    assert progress["submodules"][1]["passed"] and progress["submodules"][1]["best_score"] == 100
    assert db.scalar(select(LessonQuizVersion.submodule_id).where(
        LessonQuizVersion.quiz_id == uuid.UUID(lesson_two["quiz_id"]))) == uuid.UUID(lesson_two["id"])

    # Новый тест проходится отдельно, история не смешивается.
    session = client.post(f"/quizzes/{lesson_two_now['quiz_id']}/start", headers=learner)
    assert session.status_code == 200, session.text
    attempt = session.json()
    submitted = client.post(f"/quizzes/{lesson_two_now['quiz_id']}/submit", headers=learner, json={
        "session_id": attempt["session_id"],
        "answers": [{"question_id": q["id"], "answer": "A"} for q in attempt["questions"]],
    })
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["passed"] is True


def test_file_replacement_creates_history_without_garbage(client, db, admin_headers, make_user, storage):
    _, learner = make_user(UserRole.employee)
    state = _build_two_lesson_module(client, admin_headers, learner)
    module_id = state["module"]["id"]
    lesson_one, _ = _read_and_pass(client, learner, state)

    uploaded = client.post(f"/admin/content/modules/{module_id}/assets", headers=admin_headers,
                           data={"revision": state["module"]["content_revision"], "submodule_id": lesson_one["id"]},
                           files={"file": ("Памятка.pdf", b"%PDF-1.4 version 1", "application/pdf")})
    assert uploaded.status_code == 201, uploaded.text
    state = uploaded.json()
    asset_id = [a for a in state["assets"] if a["original_filename"] == "Памятка.pdf"][0]["asset_id"]

    replaced = client.post(f"/admin/content/modules/{module_id}/assets", headers=admin_headers,
                           data={"revision": state["module"]["content_revision"], "replace_asset_id": asset_id},
                           files={"file": ("Памятка.pdf", b"%PDF-1.4 version 2", "application/pdf")})
    assert replaced.status_code == 201, replaced.text
    state = replaced.json()

    asset = db.get(ContentAsset, uuid.UUID(asset_id))
    assert asset.version == 2
    # Старая версия сохранена как история, а не потеряна и не продублирована.
    revisions = list(db.scalars(select(AssetRevision).where(AssetRevision.asset_id == asset.id)))
    assert len(revisions) == 1 and revisions[0].object_key != asset.object_key
    assert storage.objects[revisions[0].object_key] == b"%PDF-1.4 version 1"

    assert _progress(client, learner, module_id)["completed"], "замена файла отозвала зачёт"
    files = client.get(f"/modules/submodules/{lesson_one['id']}/assets", headers=learner).json()["assets"]
    assert [item["original_filename"] for item in files] == ["Памятка.pdf"]
    assert client.get(f"/assets/{asset_id}/stream", headers=learner).content == b"%PDF-1.4 version 2"
    # Старая версия остаётся доступной для скачивания через историю файла.
    old = client.get(f"/assets/{asset_id}/download", headers=admin_headers, params={"version": 1})
    assert old.status_code in (200, 409), old.status_code


def test_permanent_lesson_delete_leaves_no_orphans(client, db, admin_headers, make_user):
    """Урок без истории удаляется целиком: ни теста, ни вопросов, ни связей."""
    _, learner = make_user(UserRole.employee)
    state = _build_two_lesson_module(client, admin_headers, learner)
    module_id = state["module"]["id"]
    lesson_two = [s for s in state["lessons"] if s["title"] == "Урок 2"][0]
    quiz_id = uuid.UUID(lesson_two["quiz_id"])

    archived = client.patch(f"/admin/content/modules/{module_id}/lessons/{lesson_two['id']}", headers=admin_headers,
                            json={"revision": state["module"]["content_revision"], "is_archived": True})
    assert archived.status_code == 200, archived.text
    state = archived.json()

    deleted = client.post(f"/admin/content/modules/{module_id}/lessons/{lesson_two['id']}/delete", headers=admin_headers,
                          json={"revision": state["module"]["content_revision"]})
    assert deleted.status_code == 200, deleted.text

    assert db.get(Submodule, uuid.UUID(lesson_two["id"])) is None
    assert db.get(Quiz, quiz_id) is None
    assert db.scalar(select(func.count()).select_from(Question).where(Question.quiz_id == quiz_id)) == 0
    assert db.scalar(select(func.count()).select_from(LessonQuizVersion).where(
        LessonQuizVersion.quiz_id == quiz_id)) == 0
    assert db.scalar(select(func.count()).select_from(SubmoduleAssetMap).where(
        SubmoduleAssetMap.submodule_id == uuid.UUID(lesson_two["id"]))) == 0
    assert db.scalar(select(func.count()).select_from(LessonRevision).where(
        LessonRevision.submodule_id == uuid.UUID(lesson_two["id"]))) == 0


def test_lesson_with_history_cannot_be_deleted(client, db, admin_headers, make_user):
    _, learner = make_user(UserRole.employee)
    state = _build_two_lesson_module(client, admin_headers, learner)
    module_id = state["module"]["id"]
    lesson_one, _ = _read_and_pass(client, learner, state)
    archived = client.patch(f"/admin/content/modules/{module_id}/lessons/{lesson_one['id']}", headers=admin_headers,
                            json={"revision": state["module"]["content_revision"], "is_archived": True})
    assert archived.status_code == 200, archived.text
    state = archived.json()
    refused = client.post(f"/admin/content/modules/{module_id}/lessons/{lesson_one['id']}/delete", headers=admin_headers,
                          json={"revision": state["module"]["content_revision"]})
    assert refused.status_code == 409, refused.text
    assert db.get(Submodule, uuid.UUID(lesson_one["id"])) is not None
    # Событие «прочитано» осталось на месте: прогресс не зависит от правок редактора.
    assert db.scalar(select(func.count()).select_from(LearningEvent).where(
        LearningEvent.ref_id == uuid.UUID(lesson_one["id"]))) >= 1
    assert db.scalar(select(func.count()).select_from(ModuleCompletion)) >= 1


def test_toggling_required_quiz_does_not_revoke_earned_module(client, db, admin_headers, make_user):
    _, learner = make_user(UserRole.employee)
    state = _build_two_lesson_module(client, admin_headers, learner)
    module_id = state["module"]["id"]
    _, lesson_two = _read_and_pass(client, learner, state)

    disabled = client.patch(f"/admin/content/modules/{module_id}/lessons/{lesson_two['id']}", headers=admin_headers,
                            json={"revision": state["module"]["content_revision"], "requires_quiz": False})
    assert disabled.status_code == 200, disabled.text
    progress = _progress(client, learner, module_id)
    assert progress["completed"], "выключение обязательного теста отозвало зачёт"
    assert progress["final_quiz_id"] is None, "без обязательных тестов итоговый тест не должен требоваться"

    enabled = client.patch(f"/admin/content/modules/{module_id}/lessons/{lesson_two['id']}", headers=admin_headers,
                           json={"revision": disabled.json()["module"]["content_revision"], "requires_quiz": True})
    assert enabled.status_code == 200, enabled.text
    again = _progress(client, learner, module_id)
    assert again["completed"] and again["current_completed"]
    assert again["submodules"][1]["passed"], "зачёт по тесту потерялся при повторном включении"


def test_repeated_lesson_open_writes_one_journal_row(client, db, admin_headers, make_user, redis_memory):
    """Открытие урока несколько раз подряд — одна запись в журнале, а не пять."""
    _, learner = make_user(UserRole.employee)
    state = _build_two_lesson_module(client, admin_headers, learner)
    lesson_one = [s for s in state["lessons"] if s["title"] == "Урок 1"][0]
    for _ in range(5):
        assert client.post(f"/submodules/{lesson_one['id']}/open", headers=learner).status_code == 200
    rows = db.scalar(select(func.count()).select_from(LearningEvent).where(
        LearningEvent.ref_id == uuid.UUID(lesson_one["id"]),
        LearningEvent.type == "submodule_opened"))
    assert rows == 1, f"открытие урока записалось {rows} раз"


def test_module_open_from_another_module_is_not_lost(client, db, admin_headers, make_user):
    """«Открытие модуля» — событие без ref_id; SQL-фильтр по модулю не должен терять чужие.

    Просмотр модуля A не должен исчезать из «продолжить обучение», когда админ
    правит модуль B: фильтр по `meta LIKE %module_id%` ограничивает выборку, но
    обязан оставаться по всем модулям сразу.
    """
    _, learner = make_user(UserRole.employee)
    first = _build_two_lesson_module(client, admin_headers, learner)
    second = _build_two_lesson_module(client, admin_headers, learner)

    for state in (first, second):
        opened = client.post(f"/modules/{state['module']['id']}/open", headers=learner)
        assert opened.status_code == 200, opened.text

    def opened_ids() -> set[str]:
        events = db.scalars(select(LearningEvent).where(LearningEvent.type == "submodule_opened",
                                                        LearningEvent.ref_id.is_(None))).all()
        return {e.meta for e in events}

    stored = " ".join(opened_ids() or [])
    assert first["module"]["id"] in stored and second["module"]["id"] in stored

    from app.services.learning import LearningService
    modules = [db.get(Module, uuid.UUID(first["module"]["id"])), db.get(Module, uuid.UUID(second["module"]["id"]))]
    learner_row = db.scalar(select(User).where(User.role == UserRole.employee))
    progress = LearningService(db)._calculate([learner_row], modules, compact=True)
    for module in modules:
        assert (learner_row.id, module.id) in progress
    # Правка одного модуля не должна «забыть» открытие другого.
    edited = client.patch(f"/admin/content/modules/{first['module']['id']}", headers=admin_headers,
                          json={"revision": first["module"]["content_revision"], "title": "Переименован"})
    assert edited.status_code == 200, edited.text
    db.expire_all()
    progress = LearningService(db)._calculate([learner_row], modules, compact=True)
    assert len(progress) == 2


def test_deleting_unfinished_lesson_does_not_grant_module_completion(client, db, admin_headers, make_user):
    """Удаление урока не должно «дописать» зачёт ученику, который модуль не проходил."""
    _, learner = make_user(UserRole.employee)
    state = _build_two_lesson_module(client, admin_headers, learner)
    module_id = state["module"]["id"]
    lesson_two = [s for s in state["lessons"] if s["title"] == "Урок 2"][0]

    archived = client.patch(f"/admin/content/modules/{module_id}/lessons/{lesson_two['id']}", headers=admin_headers,
                            json={"revision": state["module"]["content_revision"], "is_archived": True})
    assert archived.status_code == 200, archived.text
    state = archived.json()
    deleted = client.post(f"/admin/content/modules/{module_id}/lessons/{lesson_two['id']}/delete", headers=admin_headers,
                          json={"revision": state["module"]["content_revision"]})
    assert deleted.status_code == 200, deleted.text

    learner_row = db.scalar(select(User).where(User.role == UserRole.employee))
    progress = _progress(client, learner, module_id)
    assert progress["completed"] is False, "модуль зачли без единого действия ученика"
    assert progress["current_completed"] is False
    assert db.scalar(select(func.count()).select_from(ModuleCompletion).where(
        ModuleCompletion.user_id == learner_row.id,
        ModuleCompletion.module_id == uuid.UUID(module_id))) == 0
