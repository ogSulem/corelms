"""Права на изменение пользователей: админ не должен запирать сам себя.

- свою роль нельзя менять даже суперадмину (единственный суперадмин, понизивший
  себя, оставляет платформу без управления: bootstrap создаёт админа только
  когда админов нет вообще);
- свой пароль через админский сброс не меняется: там отзываются все сеансы,
  а новый пароль показывается один раз — админ запирал себя снаружи.
"""

from app.models.user import UserRole


def _superadmin(make_user):
    return make_user(UserRole.superadmin)


def test_superadmin_cannot_change_own_role(client, make_user, db):
    user, headers = _superadmin(make_user)
    response = client.patch(f"/admin/users/{user.id}", headers=headers, json={"role": "employee"})
    assert response.status_code == 400, response.text
    assert "собственную роль" in response.json()["error_message"]
    db.expire_all()
    from app.models.user import User
    assert db.get(User, user.id).role == UserRole.superadmin


def test_superadmin_can_change_other_user_role(client, make_user, db):
    _, headers = _superadmin(make_user)
    target, _ = make_user(UserRole.employee)
    response = client.patch(f"/admin/users/{target.id}", headers=headers, json={"role": "partner"})
    assert response.status_code == 200, response.text
    db.expire_all()
    from app.models.user import User
    assert db.get(User, target.id).role == UserRole.partner


def test_superadmin_can_still_edit_self_profile_fields(client, make_user, db):
    user, headers = _superadmin(make_user)
    response = client.patch(f"/admin/users/{user.id}", headers=headers,
                            json={"name": "Новое имя", "position": "Руководитель"})
    assert response.status_code == 200, response.text
    db.expire_all()
    from app.models.user import User
    row = db.get(User, user.id)
    assert row.name == "Новое имя" and row.position == "Руководитель"


def test_admin_cannot_change_role(client, admin_headers, make_user, db):
    target, _ = make_user(UserRole.employee)
    response = client.patch(f"/admin/users/{target.id}", headers=admin_headers, json={"role": "admin"})
    assert response.status_code == 403, response.text
    db.expire_all()
    from app.models.user import User
    assert db.get(User, target.id).role == UserRole.employee


def test_admin_cannot_touch_another_admin(client, admin_headers, make_user):
    other, _ = make_user(UserRole.admin)
    response = client.patch(f"/admin/users/{other.id}", headers=admin_headers, json={"name": "Взлом"})
    assert response.status_code == 403, response.text


def test_reset_password_for_self_is_refused(client, make_user):
    for role in (UserRole.admin, UserRole.superadmin):
        user, headers = make_user(role)
        response = client.post(f"/admin/users/{user.id}/reset-password", headers=headers,
                               json={"must_change_password": True})
        assert response.status_code == 400, (role, response.text)
        assert "профиле" in response.json()["error_message"]


def test_admin_can_reset_employee_password(client, admin_headers, make_user):
    target, _ = make_user(UserRole.employee)
    response = client.post(f"/admin/users/{target.id}/reset-password", headers=admin_headers,
                           json={"must_change_password": True})
    assert response.status_code == 200, response.text
    assert len(response.json()["temp_password"]) >= 12


def test_admin_cannot_reset_another_admin_password(client, admin_headers, make_user):
    other, _ = make_user(UserRole.admin)
    response = client.post(f"/admin/users/{other.id}/reset-password", headers=admin_headers, json={})
    assert response.status_code == 403, response.text
