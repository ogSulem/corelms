"""Сквозной сценарий: админ создаёт модуль с нуля, ученик проходит его целиком.

Проверяется вся цепочка, а не отдельные эндпоинты: черновик → уроки → файл →
тест → публикация → каталог ученика → чтение → тест → завершение модуля →
сводки → архив и восстановление. Любая поломка в середине цепочки должна
проявляться здесь, а не в проде.
"""

import uuid

from sqlalchemy import select

from app.models.asset import ContentAsset
from app.models.module import Module, Submodule
from app.models.submodule_asset import SubmoduleAssetMap
from app.models.user import UserRole


def _revision(workspace: dict) -> int:
    return int(workspace["module"]["content_revision"])


def _create_module(client, admin_headers, title="Модуль с нуля"):
    created = client.post("/admin/content/modules", headers=admin_headers,
                          json={"title": title, "description": "Описание", "category": "Основы"})
    assert created.status_code == 201, created.text
    return created.json()


def _lesson(workspace, lesson_id):
    for item in workspace["lessons"]:
        if str(item["id"]) == str(lesson_id):
            return item
    raise AssertionError(f"урок {lesson_id} не найден в рабочей области")


def test_admin_creates_module_and_learner_passes_it(client, db, admin_headers, make_user, storage):
    title = f"Модуль {uuid.uuid4().hex[:6]}"
    workspace = _create_module(client, admin_headers, title)

    # Новый модуль — черновик: ученик его не видит.
    learner, learner_headers = make_user(UserRole.employee)
    assert workspace["module"]["is_active"] is False
    visible = {m["title"] for m in client.get("/modules/overview", headers=learner_headers).json()["items"]}
    assert title not in visible

    # Публикация пустого модуля запрещена — иначе в каталоге появится пустая карточка.
    empty_publish = client.patch(f"/admin/content/modules/{workspace['module']['id']}", headers=admin_headers,
                                 json={"revision": _revision(workspace), "is_active": True})
    assert empty_publish.status_code == 409, empty_publish.text

    # Первый урок с текстом.
    first = client.post(f"/admin/content/modules/{workspace['module']['id']}/lessons", headers=admin_headers,
                        json={"revision": _revision(workspace), "title": "Урок 1", "content": "Текст первого урока"})
    assert first.status_code == 201, first.text
    workspace = first.json()
    lesson_one = workspace["lessons"][0]
    assert lesson_one["title"] == "Урок 1"

    # Файл модуля: загрузка через защищённый канал, затем привязка к уроку.
    asset = ContentAsset(module_id=uuid.UUID(workspace["module"]["id"]), bucket="testing",
                         object_key=f"modules/{workspace['module']['id']}/_versions/{uuid.uuid4().hex}.pdf",
                         original_filename="Инструкция.pdf", mime_type="application/pdf", version=1)
    db.add(asset)
    db.flush()
    storage.objects[asset.object_key] = b"%PDF-1.4 test"
    db.commit()

    linked = client.post(f"/admin/submodules/link-asset", headers=admin_headers,
                         json={"submodule_id": str(lesson_one["id"]), "asset_id": str(asset.id), "order": 1})
    assert linked.status_code == 200, linked.text

    # Второй урок с обязательным тестом.
    second = client.post(f"/admin/content/modules/{workspace['module']['id']}/lessons", headers=admin_headers,
                         json={"revision": _revision(workspace), "title": "Урок 2", "content": "Текст второго урока"})
    assert second.status_code == 201, second.text
    workspace = second.json()
    lesson_two = _lesson(workspace, [item for item in workspace["lessons"] if item["title"] == "Урок 2"][0]["id"])

    # Включить тест без вопросов нельзя — сначала вопросы.
    too_early = client.patch(f"/admin/content/modules/{workspace['module']['id']}/lessons/{lesson_two['id']}",
                             headers=admin_headers,
                             json={"revision": _revision(workspace), "requires_quiz": True})
    assert too_early.status_code == 409, too_early.text

    saved = client.put(f"/admin/content/modules/{workspace['module']['id']}/lessons/{lesson_two['id']}/quiz",
                       headers=admin_headers, json={
                           "revision": _revision(workspace), "enabled": True, "pass_threshold": 70,
                           "attempts_limit": 3, "time_limit": None,
                           "questions": [{
                               "type": "single", "stem": "Что делает модуль?",
                               "options": ["Обучает", "Ломается"], "correct": [0],
                               "explanation": "Потому что это обучение",
                           }],
                       })
    assert saved.status_code == 200, saved.text
    workspace = saved.json()["workspace"]
    lesson_two = _lesson(workspace, lesson_two["id"])
    assert lesson_two["requires_quiz"] is True
    assert lesson_two["question_count"] == 1

    # Публикация.
    published = client.patch(f"/admin/content/modules/{workspace['module']['id']}", headers=admin_headers,
                             json={"revision": _revision(workspace), "is_active": True, "visibility": "public"})
    assert published.status_code == 200, published.text
    workspace = published.json()
    module_id = workspace["module"]["id"]

    # ---- Ученик ------------------------------------------------------------
    overview = client.get("/modules/overview", headers=learner_headers)
    assert overview.status_code == 200
    card = next((m for m in overview.json()["items"] if m["title"] == title), None)
    assert card is not None, "опубликованный модуль не появился в каталоге ученика"
    assert card["progress"]["completed"] is False

    assert client.get(f"/modules/{module_id}", headers=learner_headers).status_code == 200
    lessons = client.get(f"/modules/{module_id}/submodules", headers=learner_headers).json()
    assert [item["title"] for item in lessons] == ["Урок 1", "Урок 2"]

    detail = client.get(f"/submodules/{lesson_one['id']}", headers=learner_headers)
    assert detail.status_code == 200 and "Текст первого урока" in detail.json()["content"]

    files = client.get(f"/modules/submodules/{lesson_one['id']}/assets", headers=learner_headers).json()["assets"]
    assert any(item["original_filename"] == "Инструкция.pdf" for item in files)
    stream = client.get(f"/assets/{asset.id}/stream", headers=learner_headers)
    assert stream.status_code == 200 and stream.content == b"%PDF-1.4 test"

    # Итоговый прогресс: сначала пусто.
    start_summary = client.get("/me/progress-summary", headers=learner_headers).json()
    assert start_summary["steps_completed"] == 0

    # Урок 1 — прочитан.
    assert client.post(f"/submodules/{lesson_one['id']}/open", headers=learner_headers).status_code == 200
    assert client.post(f"/submodules/{lesson_one['id']}/read", headers=learner_headers).json()["xp_awarded"] == 5

    # Урок 2 — сначала текст, потом тест (иначе 403).
    quiz_id = lesson_two["quiz_id"]
    assert client.post(f"/quizzes/{quiz_id}/start", headers=learner_headers).status_code == 403
    assert client.post(f"/submodules/{lesson_two['id']}/read", headers=learner_headers).status_code == 200

    session = client.post(f"/quizzes/{quiz_id}/start", headers=learner_headers)
    assert session.status_code == 200, session.text
    attempt = session.json()
    result = client.post(f"/quizzes/{quiz_id}/submit", headers=learner_headers, json={
        "session_id": attempt["session_id"],
        "answers": [{"question_id": q["id"], "answer": "A"} for q in attempt["questions"]],
    })
    assert result.status_code == 200, result.text
    assert result.json()["passed"] is True and result.json()["score"] == 100

    # Модуль завершён и это видно везде: каталог, сводка, админская аналитика.
    card = next(m for m in client.get("/modules/overview", headers=learner_headers).json()["items"] if m["title"] == title)
    assert card["progress"]["completed"] is True
    summary = client.get("/me/progress-summary", headers=learner_headers).json()
    assert summary["modules_completed"] >= 1 and summary["steps_completed"] == 2
    analytics = client.get("/admin/analytics/overview", headers=admin_headers)
    assert analytics.status_code == 200, analytics.text
    payload = analytics.json()
    assert any(row["title"] == title for row in payload["modules"])
    # Активность только что записана (SQLite отдаёт её «наивной») — страница
    # «Результаты» обязана считать active_7d, а не падать на сравнении дат.
    assert payload["totals"]["active_7d"] >= 1
    assert payload["modules"][0]["lesson_count"] >= 0
    history = client.get("/me/history?limit=50", headers=learner_headers).json()["items"]
    assert any(item.get("kind") == "quiz_attempt" for item in history)

    # ---- Архив и восстановление -------------------------------------------
    archived = client.patch(f"/admin/content/modules/{module_id}", headers=admin_headers,
                            json={"revision": _revision(workspace), "is_archived": True})
    assert archived.status_code == 200, archived.text
    assert client.get(f"/modules/{module_id}", headers=learner_headers).status_code == 404
    assert title not in {m["title"] for m in client.get("/modules/overview", headers=learner_headers).json()["items"]}

    restored = client.patch(f"/admin/content/modules/{module_id}", headers=admin_headers,
                            json={"revision": _revision(archived.json()), "is_archived": False})
    assert restored.status_code == 200, restored.text
    assert restored.json()["module"]["is_active"] is False, "восстановление не должно само публиковать модуль"

    # Прогресс не потерялся при архивации и восстановлении.
    card = next((m for m in client.get("/modules/overview", headers=learner_headers).json()["items"] if m["title"] == title), None)
    assert card is None  # после восстановления модуль снова черновик

    republished = client.patch(f"/admin/content/modules/{module_id}", headers=admin_headers,
                               json={"revision": _revision(restored.json()), "is_active": True})
    assert republished.status_code == 200, republished.text
    card = next(m for m in client.get("/modules/overview", headers=learner_headers).json()["items"] if m["title"] == title)
    assert card["progress"]["completed"] is True, "прогресс ученика потерялся после архива и восстановления"


def test_draft_is_hidden_from_learners_but_previewable_by_admin(client, db, admin_headers, make_user, storage):
    """Черновик: в каталогах его нет, ученику 404 по прямой ссылке, админ видит для превью.

    «Как видит ученик» в редакторе открывает `/modules/{id}` под админом — это
    осознанная возможность проверить модуль до публикации, поэтому админу 200.
    Всё, что выходит за пределы админской роли, должно получать 404 — иначе
    неопубликованный модуль утекает по угаданной/пересланной ссылке.
    """
    title = f"Черновик {uuid.uuid4().hex[:6]}"
    workspace = _create_module(client, admin_headers, title)
    module_id = workspace["module"]["id"]

    editor = client.get("/admin/content/modules", headers=admin_headers)
    assert editor.status_code == 200
    assert any(item["title"] == title for item in editor.json()["items"])

    lesson = client.post(f"/admin/content/modules/{module_id}/lessons", headers=admin_headers,
                         json={"revision": _revision(workspace), "title": "Скрытый урок", "content": "Секрет"})
    assert lesson.status_code == 201, lesson.text
    workspace = lesson.json()
    lesson_id = workspace["lessons"][0]["id"]

    asset = ContentAsset(module_id=uuid.UUID(module_id), bucket="testing",
                         object_key=f"modules/{module_id}/_versions/{uuid.uuid4().hex}.pdf",
                         original_filename="Секрет.pdf", mime_type="application/pdf", version=1)
    db.add(asset)
    db.flush()
    storage.objects[asset.object_key] = b"%PDF-1.4 secret"
    db.commit()
    assert client.post("/admin/submodules/link-asset", headers=admin_headers,
                       json={"submodule_id": str(lesson_id), "asset_id": str(asset.id), "order": 1}).status_code == 200

    # Превью для админа работает (редактор → «Как видит ученик»).
    as_admin, admin_reader_headers = make_user(UserRole.admin)
    assert client.get(f"/modules/{module_id}", headers=admin_reader_headers).status_code == 200
    assert client.get(f"/submodules/{lesson_id}", headers=admin_reader_headers).status_code == 200

    # Каталог черновик не показывает ни админу, ни ученику.
    for headers in (admin_reader_headers,):
        catalog = client.get("/modules", headers=headers)
        assert catalog.status_code == 200
        assert title not in {item["title"] for item in catalog.json()}

    # Любая не-админская роль не должна получить ни строчки черновика.
    for role in (UserRole.employee, UserRole.partner):
        _, headers = make_user(role)
        assert client.get("/modules", headers=headers).status_code == 200
        assert title not in {i["title"] for i in client.get("/modules", headers=headers).json()}
        assert title not in {i["title"] for i in client.get("/modules/overview", headers=headers).json()["items"]}
        for path in (
            f"/modules/{module_id}",
            f"/modules/{module_id}/submodules",
            f"/modules/{module_id}/assets",
            f"/submodules/{lesson_id}",
            f"/modules/submodules/{lesson_id}/assets",
            f"/progress/modules/{module_id}",
            f"/assets/{asset.id}/stream",
            f"/assets/{asset.id}/meta",
        ):
            response = client.get(path, headers=headers)
            assert response.status_code in (403, 404), f"{role} получил {response.status_code} на {path}"
            assert "Секрет" not in response.text and "%PDF" not in response.text
        assert client.post(f"/modules/{module_id}/open", headers=headers).status_code in (403, 404)
        assert client.post(f"/submodules/{lesson_id}/read", headers=headers).status_code in (403, 404)


def test_assignment_status_reflects_real_progress(client, db, admin_headers, make_user):
    """Назначение перестаёт быть «в работе», когда модуль пройден, и стареет по дедлайну."""
    title = f"Назначение {uuid.uuid4().hex[:6]}"
    workspace = _create_module(client, admin_headers, title)
    module_id = workspace["module"]["id"]
    lesson = client.post(f"/admin/content/modules/{module_id}/lessons", headers=admin_headers,
                         json={"revision": _revision(workspace), "title": "Урок", "content": "Текст"})
    workspace = lesson.json()
    published = client.patch(f"/admin/content/modules/{module_id}", headers=admin_headers,
                             json={"revision": _revision(workspace), "is_active": True})
    assert published.status_code == 200, published.text

    learner, learner_headers = make_user(UserRole.employee)
    created = client.post("/admin/assignments", headers=admin_headers, json={
        "assigned_to": str(learner.id), "type": "module", "target_id": module_id, "priority": 2,
        "deadline": "2020-01-01T00:00:00",
    })
    assert created.status_code == 200, created.text

    items = client.get("/me/assignments", headers=learner_headers).json()["items"]
    assignment = next(item for item in items if item["id"] == created.json()["id"])
    assert assignment["status"] == "overdue", assignment

    assert client.post(f"/submodules/{workspace['lessons'][0]['id']}/read", headers=learner_headers).status_code == 200
    items = client.get("/me/assignments", headers=learner_headers).json()["items"]
    assert next(item for item in items if item["id"] == created.json()["id"])["status"] == "completed"

    # Назначать на архивный модуль нельзя.
    archived = client.patch(f"/admin/content/modules/{module_id}", headers=admin_headers,
                            json={"revision": _revision(published.json()), "is_archived": True})
    assert archived.status_code == 200, archived.text
    again = client.post("/admin/assignments", headers=admin_headers, json={
        "assigned_to": str(learner.id), "type": "module", "target_id": module_id,
    })
    assert again.status_code == 404, again.text
