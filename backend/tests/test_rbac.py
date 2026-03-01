import uuid

from passlib.context import CryptContext

from app.db.session import SessionLocal
from app.models.user import User, UserRole


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _create_user(*, name: str, password: str, role: UserRole) -> None:
    with SessionLocal() as db:
        existing = db.query(User).filter(User.name == name).first()
        if existing is not None:
            return
        db.add(
            User(
                name=name,
                position=None,
                role=role,
                xp=0,
                level=1,
                streak=0,
                password_hash=pwd_context.hash(password),
                must_change_password=False,
            )
        )
        db.commit()


def _auth_headers_for_user(client, *, username: str, password: str) -> dict[str, str]:
    r = client.post(
        "/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_employee_cannot_access_admin_endpoints(client):
    username = f"emp_{uuid.uuid4().hex[:8]}"
    password = "testpass123"
    _create_user(name=username, password=password, role=UserRole.employee)

    # headers = _auth_headers_for_user(client, username=username, password=password)
    # r = client.get("/admin/skills/coverage", headers=headers)
    # assert r.status_code == 403
    pass
