"""Отметка «урок прочитан»: точный SQL-отбор, а не выгрузка всех открытий.

Прогресс и статус урока раньше читали ВСЕ события `submodule_opened` этого
урока (каждое открытие) и искали метку в памяти. После сотен открытий это
росло линейно. Теперь метка ищется в SQL; тест закрепляет, что смысл не
изменился: старый формат `read`, JSON `{"action": "read"}`, а простое открытие
урока прочитанным не делает.
"""

import json

from app.models.audit import LearningEvent, LearningEventType
from app.models.user import UserRole


def _progress(client, headers, module_id):
    response = client.get(f"/modules/{module_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_open_does_not_mark_lesson_read(client, db, make_module, make_user):
    module, lesson, _ = make_module()
    _, headers = make_user(UserRole.employee)

    assert client.post(f"/submodules/{lesson.id}/open", headers=headers).status_code == 200
    assert client.get(f"/submodules/{lesson.id}/read-status", headers=headers).json() == {"read": False}
    assert client.get(f"/me/progress-summary", headers=headers).json()["steps_completed"] == 0


def test_legacy_and_json_read_markers_both_count(client, db, make_module, make_user):
    module, lesson, _ = make_module()
    legacy, legacy_headers = make_user(UserRole.employee)
    modern, modern_headers = make_user(UserRole.employee)

    db.add(LearningEvent(user_id=legacy.id, type=LearningEventType.submodule_opened,
                         ref_id=lesson.id, meta="read"))
    db.add(LearningEvent(user_id=modern.id, type=LearningEventType.submodule_opened,
                         ref_id=lesson.id, meta=json.dumps({"action": "read"})))
    db.commit()

    for headers in (legacy_headers, modern_headers):
        assert client.get(f"/submodules/{lesson.id}/read-status", headers=headers).json() == {"read": True}

    # Второй раз отметка не даёт XP и не создаёт дубль.
    again = client.post(f"/submodules/{lesson.id}/read", headers=legacy_headers)
    assert again.status_code == 200 and again.json()["xp_awarded"] == 0


def test_read_marker_survives_hundreds_of_opens(client, db, make_module, make_user):
    """Метка «прочитано» не должна теряться, когда открытий стало много."""
    module, lesson, _ = make_module()
    user, headers = make_user(UserRole.employee)

    assert client.post(f"/submodules/{lesson.id}/read", headers=headers).json()["xp_awarded"] == 5
    for _ in range(120):
        db.add(LearningEvent(user_id=user.id, type=LearningEventType.submodule_opened,
                             ref_id=lesson.id, meta=json.dumps({"action": "open"})))
    db.commit()

    assert client.get(f"/submodules/{lesson.id}/read-status", headers=headers).json() == {"read": True}
    assert client.get("/me/progress-summary", headers=headers).json()["steps_completed"] >= 1


def test_read_like_meta_is_not_a_read_marker(client, db, make_module, make_user):
    """Похожие метки (`read_later`, `opened_read`) не делают урок прочитанным."""
    module, lesson, _ = make_module()
    user, headers = make_user(UserRole.employee)

    db.add(LearningEvent(user_id=user.id, type=LearningEventType.submodule_opened,
                         ref_id=lesson.id, meta=json.dumps({"action": "read_later"})))
    db.add(LearningEvent(user_id=user.id, type=LearningEventType.submodule_opened,
                         ref_id=lesson.id, meta=json.dumps({"note": "read"})))
    db.commit()

    assert client.get(f"/submodules/{lesson.id}/read-status", headers=headers).json() == {"read": False}


def test_external_link_event_rejects_non_web_schemes(client, make_user):
    _, headers = make_user(UserRole.employee)
    for url in ("javascript:alert(1)", "data:text/html,<script>", "x" * 2001, ""):
        response = client.post("/events/external-link", headers=headers, json={"url": url})
        assert response.status_code in (400, 422), (url[:30], response.text)
    ok = client.post("/events/external-link", headers=headers, json={"url": "https://example.com/a", "title": "Сайт"})
    assert ok.status_code == 200, ok.text
