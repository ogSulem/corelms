import pytest
from sqlalchemy import update

from app.models.asset import ContentAsset
from app.models.module import Module
from test_content_lifecycle import workspace
from test_quiz_lifecycle import start, submit


@pytest.fixture(autouse=True)
def hide_seed_module(db):
    db.execute(update(Module).values(is_active=False))
    db.commit()


def next_step(client, headers):
    response = client.get("/linear/next-unlocked-resolved", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_catalog_has_no_invented_module_or_progress(client, make_user):
    _, headers = make_user()
    assert next_step(client, headers) == {"state": "empty", "next": None, "modules_total": 0, "modules_completed": 0}


def test_next_step_distinguishes_lesson_quiz_and_final(client, make_user, make_module):
    module, lesson, quiz = make_module(required=True, final=True)
    _, headers = make_user()
    result = next_step(client, headers)
    assert result["state"] == "start" and result["next"]["kind"] == "lesson"
    assert result["next"]["href"] == f"/modules/{module.id}?lesson={lesson.id}"
    assert client.post(f"/submodules/{lesson.id}/read", headers=headers).status_code == 200
    result = next_step(client, headers)
    assert result["state"] == "continue" and result["next"]["href"] == f"/quizzes/{quiz.id}"
    session = start(client, headers, lesson, quiz)
    submit(client, headers, quiz.id, session)
    result = next_step(client, headers)
    assert result["next"]["kind"] == "final_quiz"
    assert result["next"]["href"] == f"/quizzes/{module.final_quiz_id}"
    assert (result["next"]["passed"], result["next"]["total"]) == (1, 2)
    assert client.get("/linear/next-unlocked", headers=headers).json() == {"submodule_id": None}


def test_file_only_module_is_a_real_next_step_then_completed(client, db, make_user, make_module):
    module, lesson, _ = make_module(folder=True)
    db.add(ContentAsset(module_id=module.id, bucket="testing", object_key="manual/a.pdf", original_filename="a.pdf"))
    db.commit()
    _, headers = make_user()
    first = next_step(client, headers)
    assert first["next"]["kind"] == "materials" and first["next"]["href"] == f"/modules/{module.id}"
    assert first["next"]["total"] == 0
    assert client.post(f"/modules/{module.id}/open", headers=headers).status_code == 200
    result = next_step(client, headers)
    assert result["state"] == "completed" and result["next"] is None


def test_new_lesson_is_update_not_a_lost_completion(client, db, make_user, make_module, admin_headers):
    module, lesson, _ = make_module()
    _, headers = make_user()
    assert client.post(f"/submodules/{lesson.id}/read", headers=headers).status_code == 200
    assert next_step(client, headers)["state"] == "completed"
    state = workspace(client, admin_headers, module.id)
    result = client.post(f"/admin/content/modules/{module.id}/lessons", headers=admin_headers,
                         json={"revision": state["module"]["content_revision"], "title": "Дополнение", "content": "Новое"})
    assert result.status_code == 201
    candidate = next_step(client, headers)
    assert candidate["state"] == "updates" and candidate["next"]["completed"]
    assert candidate["next"]["submodule_title"] == "Дополнение" and candidate["modules_completed"] == 1


def test_file_updates_are_notified_until_the_new_revision_is_opened(client, db, make_user, make_module, admin_headers, storage):
    module, lesson, _ = make_module()
    _, headers = make_user()
    assert client.post(f"/submodules/{lesson.id}/read", headers=headers).status_code == 200
    state = workspace(client, admin_headers, module.id)
    result = client.post(f"/admin/content/modules/{module.id}/assets", headers=admin_headers,
                         data={"revision": state["module"]["content_revision"]}, files={"file": ("Новое.txt", b"New")})
    assert result.status_code == 201, result.text
    assert next_step(client, headers)["state"] == "updates"
    assert client.post(f"/modules/{module.id}/open", headers=headers).status_code == 200
    assert next_step(client, headers)["state"] == "completed"


def test_recent_unfinished_module_is_preferred_and_private_modules_never_leak(client, db, make_user, make_module):
    first, _, _ = make_module(title="01. Первый")
    second, lesson, _ = make_module(title="02. Второй")
    hidden, _, _ = make_module(title="Скрытый")
    hidden.visibility = "restricted"
    db.commit()
    _, headers = make_user()
    assert next_step(client, headers)["next"]["module_id"] == str(first.id)
    assert client.post(f"/modules/{second.id}/open", headers=headers).status_code == 200
    result = next_step(client, headers)
    assert result["next"]["module_id"] == str(second.id) and result["modules_total"] == 2
    second.is_archived = True
    db.commit()
    assert next_step(client, headers)["next"]["module_id"] == str(first.id)
