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

# Tests never require a production .env or live services.
for key, value in {
    "DATABASE_URL": "sqlite+pysqlite:///:memory:", "REDIS_URL": "redis://localhost:6379/15",
    "MEDIA_DISPATCHER_ENABLED": "false",
    "JWT_SECRET_KEY": "test-only-not-a-production-secret", "CORS_ALLOW_ORIGINS": "http://testserver",
    "S3_ENDPOINT_URL": "http://storage.test", "S3_ACCESS_KEY_ID": "testing",
    "S3_SECRET_ACCESS_KEY": "testing", "S3_BUCKET": "testing", "APP_ENV": "development",
}.items():
    os.environ.setdefault(key, value)

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
from app.models.completion import ModuleCompletion, LessonQuizVersion  # noqa: F401
from app.models.media import AssetRendition  # noqa: F401
from app.models.sales import SalesEntry, SalesSection  # noqa: F401
from app.models.asset import AssetRevision, ContentAsset  # noqa: F401
from app.models.submodule_asset import SubmoduleAssetMap  # noqa: F401
from app.models.security_audit import SecurityAuditEvent  # noqa: F401



# Configure test DB (SQLite in-memory) at import time so all tests importing
# app.db.session.SessionLocal will get the patched version.
_test_url = os.environ.get("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
_engine = create_engine(_test_url, **({"connect_args": {"check_same_thread": False}, "poolclass": StaticPool} if _test_url.startswith("sqlite") else {}))
if _test_url.startswith("sqlite"):
    from sqlalchemy import event
    @event.listens_for(_engine, "connect")
    def _sqlite_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
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


# The per-test schema fixture seeds content after recreating the disposable DB.

# Stub Redis at import time (rate limiting + quiz sessions).
import fakeredis
_mem_redis = fakeredis.FakeRedis(decode_responses=True)
import app.core.redis_client as redis_client_module

redis_client_module.get_redis = lambda: _mem_redis

import app.core.rate_limit as rate_limit_module
rate_limit_module.get_redis = lambda: _mem_redis

import app.routers.quizzes as quizzes_router_module
quizzes_router_module.get_redis = lambda: _mem_redis

import app.routers.auth as auth_router_module


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


@pytest.fixture(autouse=True)
def fake_redis_everywhere(monkeypatch):
    _mem_redis.flushdb()
    for name, module in list(sys.modules.items()):
        if name.startswith("app."):
            if hasattr(module, "get_redis"):
                monkeypatch.setattr(module, "get_redis", lambda: _mem_redis)
            if hasattr(module, "SessionLocal"):
                monkeypatch.setattr(module, "SessionLocal", session_module.SessionLocal)


@pytest.fixture(autouse=True)
def isolated_content():
    # Every scenario starts from the same small baseline; no cross-test quiz state.
    Base.metadata.drop_all(bind=_engine)
    Base.metadata.create_all(bind=_engine)
    if _engine.dialect.name == "postgresql":
        # Dropped native enums receive new OIDs. Discard pooled prepared
        # statements after each destructive reset of the disposable schema.
        _engine.dispose()
    _seed_minimal_content()


@pytest.fixture()
def redis_memory():
    return _mem_redis


@pytest.fixture()
def make_user(db):
    from app.core.tokens import create_access_token
    from app.services.auth_sessions import issue_session
    from starlette.requests import Request
    from app.models.user import UserRole
    def create(role=UserRole.employee):
        user = User(name=f"user_{uuid.uuid4().hex[:10]}", role=role, password_hash="test-only", must_change_password=False)
        db.add(user)
        db.commit()
        _, _, sid = issue_session(user, Request({"type": "http", "headers": [], "client": ("testclient", 0)}))
        token = create_access_token(user, sid)
        return user, {"Authorization": f"Bearer {token}"}
    return create


@pytest.fixture()
def admin_headers(make_user):
    from app.models.user import UserRole
    return make_user(UserRole.admin)[1]


@pytest.fixture()
def make_module(db):
    from app.models.quiz import Quiz, QuizType, Question, QuestionType
    def create(*, title=None, required=False, active=True, folder=False, final=False, content="Теория урока", question_count=1):
        quiz = Quiz(type=QuizType.submodule, pass_threshold=70, attempts_limit=3)
        db.add(quiz)
        if final:
            final_quiz = Quiz(type=QuizType.final, pass_threshold=70, attempts_limit=3)
            db.add(final_quiz)
        db.flush()
        module = Module(title=title or f"Модуль {uuid.uuid4().hex[:8]}", is_active=active,
                        visibility="public", final_quiz_id=final_quiz.id if final else None)
        db.add(module)
        db.flush()
        lesson = Submodule(module_id=module.id, title="Урок", order=1, quiz_id=quiz.id,
                           requires_quiz=required, is_folder=folder, content=content)
        db.add(lesson)
        for i in range(question_count):
            db.add(Question(quiz_id=quiz.id, type=QuestionType.single, difficulty=1,
                            prompt=f"Вопрос {i + 1}\nA) Верно\nB) Неверно", correct_answer="A", concept_tag="ok:test"))
        db.commit()
        return module, lesson, quiz
    return create


@pytest.fixture()
def storage(monkeypatch):
    import io
    from botocore.exceptions import ClientError
    from app.core.config import settings
    import app.services.module_importer  # register references before patching
    import app.services.module_import_jobs
    import app.services.storage_cleanup_jobs
    class Store:
        def __init__(self):
            self.objects = {}
            self.deleted = []
            self.uploaded = []
            self.bodies = []
        def head_object(self, *, Bucket, Key):
            if Key not in self.objects:
                raise ClientError({"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "HeadObject")
            return {"ContentLength": len(self.objects[Key]), "ETag": '"test-etag"'}
        def get_object(self, *, Bucket, Key, Range=None):
            self.head_object(Bucket=Bucket, Key=Key)
            original = data = self.objects[Key]
            start, end = 0, len(data) - 1
            if Range:
                left, right = Range.removeprefix("bytes=").split("-")
                start = int(left) if left else max(0, len(data) - int(right))
                end = min(int(right), len(data) - 1) if left and right else len(data) - 1
                data = data[start:end + 1]
            body = io.BytesIO(data)
            self.bodies.append(body)
            result = {"Body": body, "ContentLength": len(data)}
            if Range:
                result["ContentRange"] = f"bytes {start}-{end}/{len(original)}"
            return result
        def delete_object(self, *, Bucket, Key):
            self.deleted.append(Key)
            self.objects.pop(Key, None)
        def upload(self, *, s3, object_key, fileobj, **kwargs):
            self.uploaded.append(object_key)
            self.objects[object_key] = fileobj.read()
        def put_object(self, *, Bucket, Key, Body, **kwargs):
            self.objects[Key] = Body.read() if hasattr(Body, "read") else bytes(Body)
            self.uploaded.append(Key)
        def list_objects_v2(self, *, Bucket, Prefix, **kwargs):
            from datetime import datetime, timezone, timedelta
            entries = {}
            delimiter = kwargs.get("Delimiter")
            for key, value in sorted(self.objects.items()):
                if not key.startswith(Prefix):
                    continue
                tail = key[len(Prefix):]
                if delimiter and delimiter in tail:
                    folder = Prefix + tail.split(delimiter, 1)[0] + delimiter
                    entries[folder] = ("folder", {"Prefix": folder})
                else:
                    entries[key] = ("file", {"Key": key, "LastModified": datetime.now(timezone.utc) - timedelta(days=100), "Size": len(value)})
            start = int(kwargs.get("ContinuationToken") or 0)
            maximum = int(kwargs.get("MaxKeys") or 1000)
            items = sorted(entries.items())[start:start + maximum]
            result = {"Contents": [value for _, (kind, value) in items if kind == "file"],
                      "CommonPrefixes": [value for _, (kind, value) in items if kind == "folder"],
                      "IsTruncated": start + maximum < len(entries)}
            if result["IsTruncated"]:
                result["NextContinuationToken"] = str(start + maximum)
            return result
    store = Store()
    for name, module in list(sys.modules.items()):
        if not name.startswith("app."):
            continue
        for attr, value in {"get_s3_client": lambda: store, "ensure_bucket_exists": lambda: None,
                            "upload_fileobj_with_retry": store.upload,
                            "presign_get": lambda **kwargs: "https://storage.test/" + kwargs["object_key"]}.items():
            if hasattr(module, attr):
                monkeypatch.setattr(module, attr, value)
    return store
