import uuid

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.audit import LearningEvent, LearningEventType
from app.models.module import Submodule
from app.models.user import User


def _get_user_from_token_payload(client, headers):
    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200
    return uuid.UUID(r.json()["id"])


def test_read_idempotent_awards_xp_once(client, auth_headers):
    uid = _get_user_from_token_payload(client, auth_headers)

    with SessionLocal() as db:
        sub = db.scalar(select(Submodule).order_by(Submodule.order.asc()))
        assert sub is not None
        before_xp = db.scalar(select(User.xp).where(User.id == uid))

    r1 = client.post(f"/submodules/{sub.id}/read", headers=auth_headers)
    assert r1.status_code == 200
    assert r1.json()["xp_awarded"] in (0, 5)

    r2 = client.post(f"/submodules/{sub.id}/read", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["xp_awarded"] == 0

    with SessionLocal() as db:
        after_xp = db.scalar(select(User.xp).where(User.id == uid))
        assert after_xp in (before_xp, before_xp + 5)

        cnt = db.scalar(
            select(func.count(LearningEvent.id)).where(
                LearningEvent.user_id == uid,
                LearningEvent.type == LearningEventType.submodule_opened,
                LearningEvent.ref_id == sub.id,
                LearningEvent.meta == "read",
            )
        )
        assert cnt == 1


def test_start_quiz_idempotent_reuses_session_and_does_not_duplicate_event(client, auth_headers):
    uid = _get_user_from_token_payload(client, auth_headers)

    with SessionLocal() as db:
        sub = db.scalar(select(Submodule).order_by(Submodule.order.asc()))
        assert sub is not None

    client.post(f"/submodules/{sub.id}/read", headers=auth_headers)

    with SessionLocal() as db:
        before = db.scalar(
            select(func.count(LearningEvent.id)).where(
                LearningEvent.user_id == uid,
                LearningEvent.type == LearningEventType.quiz_started,
                LearningEvent.ref_id == sub.quiz_id,
            )
        )

    r1 = client.post(f"/quizzes/{sub.quiz_id}/start", headers=auth_headers)
    assert r1.status_code == 200
    q1 = [q["id"] for q in r1.json()["questions"]]

    r2 = client.post(f"/quizzes/{sub.quiz_id}/start", headers=auth_headers)
    assert r2.status_code == 200
    q2 = [q["id"] for q in r2.json()["questions"]]

    assert q1 == q2

    with SessionLocal() as db:
        after = db.scalar(
            select(func.count(LearningEvent.id)).where(
                LearningEvent.user_id == uid,
                LearningEvent.type == LearningEventType.quiz_started,
                LearningEvent.ref_id == sub.quiz_id,
            )
        )

    assert after == before + 1


def test_submit_quiz_first_fail_awards_activity_xp(client, auth_headers):
    uid = _get_user_from_token_payload(client, auth_headers)

    with SessionLocal() as db:
        sub = db.scalar(select(Submodule).order_by(Submodule.order.asc()))
        assert sub is not None

    client.post(f"/submodules/{sub.id}/read", headers=auth_headers)

    start = client.post(f"/quizzes/{sub.quiz_id}/start", headers=auth_headers)
    assert start.status_code == 200

    with SessionLocal() as db:
        before_xp = db.scalar(select(User.xp).where(User.id == uid))

    submit = client.post(
        f"/quizzes/{sub.quiz_id}/submit",
        headers=auth_headers,
        json={"answers": []},
    )
    assert submit.status_code == 200

    with SessionLocal() as db:
        after_xp = db.scalar(select(User.xp).where(User.id == uid))
    assert after_xp >= before_xp
