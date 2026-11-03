"""Замер стоимости сохранения и прогресса на объёме (только локально).

Отвечает на вопрос «не сохраняется ли долго»: сколько стоит пересчёт прогресса
после правки урока, как быстро открывается редактор модуля и матрица прогресса.

Безопасен: база принудительно подменяется на SQLite в памяти, реальные
DATABASE_URL/S3 из окружения не используются. Запуск из `backend/`:

    PYTHONPATH=. python scripts/bench_learning.py
"""

import json
import os
import statistics
import time
import uuid

# Принудительно: сценарный замер не должен попасть в боевую базу.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET_KEY", "b" * 40)
os.environ.setdefault("CORS_ALLOW_ORIGINS", '["http://localhost:3000"]')
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:9000")
os.environ.setdefault("S3_ACCESS_KEY_ID", "k")
os.environ.setdefault("S3_SECRET_ACCESS_KEY", "s")
os.environ.setdefault("S3_BUCKET", "b")

from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
import pkgutil
import importlib
import app.models as _models_pkg
import app.db.base  # noqa: F401
for _info in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"app.models.{_info.name}")
from app.models.audit import LearningEvent, LearningEventType  # noqa: E402
from app.models.completion import ModuleCompletion  # noqa: E402
from app.models.module import Module, Submodule  # noqa: E402
from app.models.quiz import Question, Quiz, QuizType  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.services.learning import LearningService  # noqa: E402


def build(users=500, lessons=40, events_per_user=20):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        module = Module(title="Нагрузка", is_active=True, visibility="public")
        db.add(module)
        db.flush()
        subs = []
        for index in range(lessons):
            quiz = Quiz(type=QuizType.submodule)
            db.add(quiz)
            db.flush()
            db.add(Question(quiz_id=quiz.id, type="single", position=1, prompt="Q", correct_answer="A"))
            sub = Submodule(module_id=module.id, title=f"Урок {index}", order=index + 1, quiz_id=quiz.id,
                            requires_quiz=False, content="текст")
            db.add(sub)
            subs.append(sub)
        db.flush()
        rows = []
        for u in range(users):
            user = User(name=f"Ученик {u}", email=f"u{u}@example.test", password_hash="x", role=UserRole.employee)
            db.add(user)
            db.flush()
            for index, sub in enumerate(subs[:events_per_user]):
                rows.append(LearningEvent(user_id=user.id, type=LearningEventType.submodule_opened,
                                          ref_id=sub.id, meta="read"))
            rows.append(LearningEvent(user_id=user.id, type=LearningEventType.submodule_opened, ref_id=None,
                                      meta=json.dumps({"action": "module_open", "module_id": str(module.id),
                                                       "content_revision": 1, "learning_revision": 1})))
        db.bulk_save_objects(rows)
        db.commit()
        return module.id, [s.id for s in subs]


def build_assets(module_id, lessons, count=300):
    from app.models.asset import ContentAsset
    from app.models.submodule_asset import SubmoduleAssetMap
    with SessionLocal() as db:
        for index in range(count):
            asset = ContentAsset(module_id=module_id, bucket="b", object_key=f"modules/x/{index}.pdf",
                                 original_filename=f"Файл {index}.pdf", mime_type="application/pdf",
                                 size_bytes=1000, order=index)
            db.add(asset)
            db.flush()
            if index < len(lessons) * 5:
                db.add(SubmoduleAssetMap(submodule_id=lessons[index % len(lessons)], asset_id=asset.id, order=index))
        db.commit()


def measure(label, fn, rounds=5):
    times = []
    for _ in range(rounds):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    print(f"{label}: медиана {statistics.median(times):.0f} мс, макс {max(times):.0f} мс")
    return statistics.median(times)


def main():
    module_id, lesson_ids = build()
    with SessionLocal() as db:
        module = db.get(Module, module_id)
        learner = db.query(User).first()

        def save_lesson():
            LearningService(db).remember_completions(module)
            db.rollback()

        measure("remember_completions (500 учеников × 40 уроков)", save_lesson, rounds=3)

        def progress_one():
            LearningService(db).get_module_progress(learner, module_id)
            db.rollback()

        measure("прогресс одного модуля для одного ученика", progress_one)

        def progress_matrix():
            users = db.query(User).all()
            LearningService(db).get_progress_matrix(users, [module])
            db.rollback()

        measure("матрица прогресса (500 учеников × модуль)", progress_matrix, rounds=3)
        build_assets(module_id, lesson_ids, 300)
        db.expire_all()
        module = db.get(Module, module_id)
        admin = db.query(User).first()

        def save_lesson_screen():
            from app.services.content import workspace
            workspace(db, module)   # ответ на каждое сохранение урока
            db.rollback()

        measure("ответ редактора модуля (300 файлов)", save_lesson_screen, rounds=3)
        print("достижений в базе:", db.query(ModuleCompletion).count())


if __name__ == "__main__":
    main()
