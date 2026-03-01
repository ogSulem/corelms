import os
import sys
from pathlib import Path
import uuid
import time

import pytest
from fastapi.testclient import TestClient

backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db import session as session_module
from app.main import create_app

# Import models so that they are registered in Base.metadata before create_all.
from app.models.user import User  # noqa: F401
from app.models.skill import SkillCategory, Skill, UserSkill  # noqa: F401
from app.models.module import Module, ModuleSkillMap, Submodule  # noqa: F401
from app.models.quiz import Quiz, Question  # noqa: F401
from app.models.assignment import Assignment  # noqa: F401
from app.models.knowledge import KnowledgeArticle  # noqa: F401
from app.models.attempt import QuizAttempt, QuizAttemptAnswer  # noqa: F401
from app.models.audit import LearningEvent  # noqa: F401
from app.models.asset import ContentAsset  # noqa: F401
from app.models.submodule_asset import SubmoduleAssetMap  # noqa: F401
from app.models.security_audit import SecurityAuditEvent  # noqa: F401


class _MemoryRedis:
    def __init__(self):
        self._data: dict[str, tuple[str, float | None]] = {}

    def ping(self):
        return True

    def _now(self) -> float:
        return time.time()

    def _get_entry(self, key: str):
        v = self._data.get(key)
        if not v:
            return None
        value, exp = v
        if exp is not None and exp <= self._now():
            self._data.pop(key, None)
            return None
        return value, exp

    def get(self, key: str):
        entry = self._get_entry(key)
        return entry[0] if entry else None

    def set(self, key: str, value: str, ex: int | None = None):
        exp = (self._now() + int(ex)) if ex else None
        self._data[key] = (value, exp)
        return True

    def delete(self, key: str):
        self._data.pop(key, None)
        return 1

    def incr(self, key: str):
        cur = self.get(key)
        n = int(cur or 0) + 1
        _, exp = self._data.get(key, ("", None))
        self._data[key] = (str(n), exp)
        return n

    def expire(self, key: str, seconds: int):
        entry = self._get_entry(key)
        if not entry:
            return False
        value, _ = entry
        self._data[key] = (value, self._now() + int(seconds))
        return True

    def ttl(self, key: str):
        entry = self._get_entry(key)
        if not entry:
            return -2
        _, exp = entry
        if exp is None:
            return -1
        return max(0, int(exp - self._now()))


# Configure test DB (SQLite in-memory) at import time so all tests importing
# app.db.session.SessionLocal will get the patched version.
_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=_engine)
session_module.engine = _engine
session_module.SessionLocal = session_module.sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _seed_minimal_content() -> None:
    # Ensure at least one module/submodule/quiz/question exists for invariants tests.
    from sqlalchemy import select

    from app.models.module import Module, Submodule
    from app.models.quiz import Quiz, QuizType, Question, QuestionType

    with session_module.SessionLocal() as db:
        existing_sub = db.scalar(select(Submodule).limit(1))
        if existing_sub is not None:
            return

        q = Quiz(type=QuizType.submodule, pass_threshold=70, time_limit=None, attempts_limit=3)
        db.add(q)
        db.flush()

        db.add(
            Question(
                quiz_id=q.id,
                type=QuestionType.single,
                difficulty=1,
                prompt="Test question\nA) 1\nB) 2",
                correct_answer="A",
                explanation=None,
                concept_tag="test_q1",
                variant_group=None,
            )
        )

        m = Module(title="Test module", description=None, difficulty=1, category=None, is_active=True)
        db.add(m)
        db.flush()

        db.add(Submodule(module_id=m.id, title="Test submodule", order=1, quiz_id=q.id, content="test"))
        db.commit()


_seed_minimal_content()


# Stub Redis at import time (rate limiting + quiz sessions).
_mem_redis = _MemoryRedis()
import app.core.redis_client as redis_client_module

redis_client_module.get_redis = lambda: _mem_redis

import app.core.rate_limit as rate_limit_module
rate_limit_module.get_redis = lambda: _mem_redis

import app.routers.quizzes as quizzes_router_module
quizzes_router_module.get_redis = lambda: _mem_redis

import app.routers.health as health_router_module
health_router_module.get_redis = lambda: _mem_redis


@pytest.fixture(scope="session")
def client():
    app = create_app()

    # Ensure app dependencies use our session factory.
    def _get_db_override():
        db = session_module.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[session_module.get_db] = _get_db_override
    return TestClient(app)


@pytest.fixture()
def db():
    with session_module.SessionLocal() as session:
        yield session


@pytest.fixture()
def user_token(client, monkeypatch):
    from app.core.config import settings
    username = f"test_{uuid.uuid4().hex[:8]}"
    password = "testpass123"

    monkeypatch.setattr(settings, "allow_public_register", True)
    r = client.post(
        "/auth/register",
        json={"name": username, "position": None, "role": "employee", "password": password},
    )
    assert r.status_code in (200, 409)

    r = client.post(
        "/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200
    token = r.json()["access_token"]
    return token


@pytest.fixture()
def auth_headers(user_token):
    return {"Authorization": f"Bearer {user_token}"}
