"""Run only against an explicitly supplied, disposable PostgreSQL database."""
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


@pytest.mark.skipif(not os.getenv("TEST_MIGRATION_DATABASE_URL"), reason="requires disposable PostgreSQL migration database")
def test_legacy_upgrade_backfills_completion_and_asset_ownership(monkeypatch):
    from app.core.config import settings
    url = os.environ["TEST_MIGRATION_DATABASE_URL"]
    engine = create_engine(url)
    with engine.begin() as connection:
        # This database must be isolated from application data and the main test DB.
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    monkeypatch.setattr(settings, "database_url", url)
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, "0020")
    uid, newcomer, mid, sid, qid, aid, general = [uuid.uuid4() for _ in range(7)]
    values = dict(uid=uid, newcomer=newcomer, mid=mid, sid=sid, qid=qid, aid=aid, general=general)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id,name,role,password_hash) VALUES (:uid,'Completed learner','employee','test'),(:newcomer,'New learner','employee','test')"), values)
        connection.execute(text("INSERT INTO quizzes (id,type) VALUES (:qid,'submodule')"), values)
        connection.execute(text("INSERT INTO modules (id,title,is_active,storage_prefix) VALUES (:mid,'Legacy module',true,'modules/legacy/')"), values)
        connection.execute(text('INSERT INTO submodules (id,module_id,title,"order",quiz_id,content,requires_quiz,is_folder) VALUES (:sid,:mid,\'Legacy lesson\',1,:qid,\'Theory\',false,false)'), values)
        connection.execute(text("INSERT INTO learning_events (id,user_id,type,ref_id,meta) VALUES (:event,:uid,'submodule_opened',:sid,:meta)"),
                           {**values, "event": uuid.uuid4(), "meta": '{"action": "read"}'})
        connection.execute(text("INSERT INTO content_assets (id,bucket,object_key,original_filename) VALUES (:aid,'testing','modules/legacy/lesson/a.csv','a.csv'),(:general,'testing','modules/legacy/_module/general.csv','general.csv')"), values)
        connection.execute(text('INSERT INTO submodule_asset_map (submodule_id,asset_id,"order") VALUES (:sid,:aid,1)'), values)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # Running a deploy twice is safe.
    with engine.connect() as connection:
        completions = connection.execute(text("SELECT user_id,module_id,content_revision FROM module_completions")).all()
        assert completions == [(uid, mid, 1)]
        assert connection.execute(text("SELECT module_id FROM content_assets WHERE id IN (:aid,:general)"), values).scalars().all() == [mid, mid]
        assert connection.execute(text("SELECT submodule_id FROM lesson_quiz_versions WHERE quiz_id=:qid"), values).scalar_one() == sid
        assert connection.execute(text("SELECT content_revision FROM modules WHERE id=:mid"), values).scalar_one() == 1
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0026"
        assert connection.execute(text("SELECT content_mode, content_version FROM submodules WHERE id=:sid"), values).one() == ("manual", 1)
        assert connection.execute(text("SELECT count(*) FROM lesson_revisions")).scalar_one() == 0
        assert connection.execute(text("SELECT presentation_mode, primary_asset_id FROM submodules WHERE id=:sid"), values).one() == ("auto", None)
        assert connection.execute(text("SELECT final_quiz_enabled FROM modules WHERE id=:mid"), values).scalar_one() is True
        assert connection.execute(text("SELECT name, revision FROM sales_sections ORDER BY name")).all() == [("catalogs", 1), ("photos", 1)]
        assert connection.execute(text("SELECT count(*) FROM asset_renditions")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM asset_thumbs")).scalar_one() == 0
    # The reverse migration is structurally valid, but intentionally loses the new
    # lifecycle metadata; production rollback must restore a DB backup instead.
    command.downgrade(cfg, "0020")
    command.upgrade(cfg, "head")
    engine.dispose()
