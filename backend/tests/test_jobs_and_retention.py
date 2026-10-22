import io
import json
import uuid
import zipfile
from types import SimpleNamespace

import pytest
from rq.job import JobStatus
from sqlalchemy import func, select

from app.core.queue import normalize_job_status, release_job_lock
from app.db.session import SessionLocal
from app.models.asset import AssetRevision, ContentAsset
from app.models.module import Module, Submodule
from app.models.quiz import Question, Quiz


class Job:
    def __init__(self, status=JobStatus.QUEUED, **meta):
        self.id = uuid.uuid4().hex
        self.meta = meta
        self.status = status
        self.cancel_called = False
        self.result = None
        self.enqueued_at = self.started_at = self.ended_at = None
        self.exc_info = None
        self.origin = "corelms_import"
    def get_status(self, refresh=True):
        return self.status
    def save_meta(self):
        pass
    def refresh(self):
        pass
    def cancel(self):
        self.cancel_called = True
        self.status = JobStatus.CANCELED


@pytest.mark.parametrize("status", list(JobStatus))
def test_real_rq_enum_status_is_normalized(status):
    assert normalize_job_status(status) == status.value
    assert normalize_job_status(str(status)) == status.value


def test_lock_release_never_removes_another_job(redis_memory):
    redis_memory.set("lease", "second")
    release_job_lock(redis_memory, "lease", "first")
    assert redis_memory.get("lease") == "second"
    release_job_lock(redis_memory, "lease", "second")
    assert redis_memory.get("lease") is None


def test_cancel_running_job_keeps_content_source_and_lease(client, db, admin_headers, make_module, storage, redis_memory, monkeypatch):
    from app.routers import admin
    module, lesson, quiz = make_module()
    job = Job(JobStatus.STARTED, job_kind="import", module_id=str(module.id), import_object_key="uploads/source.zip")
    storage.objects["uploads/source.zip"] = b"zip bytes"
    redis_memory.set(f"content:import:{module.id}", job.id)
    redis_memory.set("admin:import_enqueued_by_object_key:uploads/source.zip", job.id)
    monkeypatch.setattr(admin, "fetch_job", lambda _: job)
    response = client.post(f"/admin/jobs/{job.id}/cancel?delete_source_zip=true", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "started"
    assert job.meta["cancel_requested"] and not job.cancel_called
    assert redis_memory.get(f"content:import:{module.id}") == job.id
    assert db.get(Module, module.id) and db.get(Submodule, lesson.id) and db.get(Quiz, quiz.id)
    assert storage.objects["uploads/source.zip"] == b"zip bytes" and not storage.deleted


def test_queued_cancel_releases_only_its_own_lease(client, admin_headers, make_module, redis_memory, monkeypatch):
    from app.routers import admin
    module, _, _ = make_module()
    job = Job(job_kind="import", module_id=str(module.id), import_object_key="uploads/source.zip")
    redis_memory.set(f"content:import:{module.id}", "a-newer-job")
    redis_memory.set("admin:import_enqueued_by_object_key:uploads/source.zip", job.id)
    monkeypatch.setattr(admin, "fetch_job", lambda _: job)
    assert client.post(f"/admin/jobs/{job.id}/cancel", headers=admin_headers).status_code == 200
    assert job.cancel_called
    assert redis_memory.get(f"content:import:{module.id}") == "a-newer-job"
    assert redis_memory.get("admin:import_enqueued_by_object_key:uploads/source.zip") is None


def zip_bytes():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("Материал.txt", "Новая инструкция")
    return stream.getvalue()


def test_reimport_deduplicates_before_upload_and_metadata_exists_at_enqueue(client, admin_headers, make_module, storage, redis_memory, monkeypatch):
    from app.routers import content, admin
    module, _, _ = make_module()
    jobs = {}
    def enqueue(function, **kwargs):
        assert kwargs["meta"]["module_id"] == str(module.id)
        assert kwargs["reimport_existing"] and kwargs["enqueue_regen"] is False
        assert kwargs["expected_revision"] == module.content_revision
        job = Job(**kwargs["meta"])
        job.id = kwargs["job_id"]
        jobs[job.id] = job
        return job
    monkeypatch.setattr(content, "get_queue", lambda _: SimpleNamespace(enqueue=enqueue))
    monkeypatch.setattr(content, "fetch_job", lambda jid: jobs.get(jid))
    monkeypatch.setattr(admin, "fetch_job", lambda jid: jobs.get(jid))
    def send():
        return client.post(f"/admin/content/modules/{module.id}/reimport", headers=admin_headers,
                           data={"revision": module.content_revision}, files={"file": ("module.zip", zip_bytes())})
    first, second = send(), send()
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert second.json()["reused"]
    assert len(jobs) == len(storage.uploaded) == 1
    jid = first.json()["job_id"]
    assert redis_memory.get(f"content:import:{module.id}") == jid
    snapshot = client.get(f"/admin/jobs/{jid}", headers=admin_headers)
    assert snapshot.status_code == 200 and snapshot.json()["status"] == "queued"
    # Legacy retry must not turn a targeted update into a brand new module.
    retry = client.post(f"/admin/import-jobs/{jid}/retry", headers=admin_headers)
    assert retry.status_code == 409
    jobs[jid].status = JobStatus.FAILED
    third = send()
    assert third.status_code == 202 and third.json()["job_id"] != jid
    assert len(jobs) == 2


def test_worker_download_failure_releases_lease_but_never_module(make_module, storage, redis_memory, monkeypatch):
    from app.services import module_import_jobs as jobs
    module, _, _ = make_module()
    job = Job(JobStatus.STARTED, module_id=str(module.id), import_object_key="missing.zip")
    monkeypatch.setattr(jobs, "get_current_job", lambda: job)
    redis_memory.set(f"content:import:{module.id}", job.id)
    with pytest.raises(Exception):
        jobs.import_module_zip_job(s3_object_key="missing.zip", module_id=str(module.id), reimport_existing=True)
    assert redis_memory.get(f"content:import:{module.id}") is None
    with SessionLocal() as db:
        assert db.get(Module, module.id) is not None
    assert not storage.deleted


def test_cleanup_and_manual_delete_protect_versions(client, db, admin_headers, make_module, storage):
    from app.services.storage_cleanup_jobs import cleanup_admin_uploads_job
    module, _, _ = make_module()
    original, current = "uploads/admin/original.csv", "uploads/admin/current.csv"
    asset = ContentAsset(module_id=module.id, bucket="testing", object_key=current, original_filename="current.csv", version=2)
    db.add(asset)
    db.flush()
    db.add(AssetRevision(asset_id=asset.id, version=1, bucket="testing", object_key=original, original_filename="original.csv"))
    db.commit()
    for key in [original, current, "uploads/admin/source.zip", "uploads/admin/trash.tmp"]:
        storage.objects[key] = b"bytes"
    storage.delete_objects = lambda *, Bucket, Delete: [storage.delete_object(Bucket=Bucket, Key=x["Key"]) for x in Delete["Objects"]]
    report = cleanup_admin_uploads_job(ttl_hours=1)
    assert report["deleted_objects"] == 0 and storage.deleted == []
    assert report["candidate_objects"] == 1 and report["retention_policy"] == "report_only"
    for key in [original, current]:
        for route in ["/admin/storage/object/delete", "/admin/modules/abort-import-zip"]:
            response = client.post(route, headers=admin_headers, json={"object_key": key})
            assert response.status_code == 409, (route, response.text)
    assert storage.objects[original] and storage.objects[current]
    with pytest.raises(ValueError):
        cleanup_admin_uploads_job(prefix="modules/")


@pytest.mark.parametrize("kind", ["module", "lesson"])
def test_old_queued_regeneration_cannot_publish_without_author_review(db, make_module, kind):
    from app.services import quiz_regeneration_jobs as jobs
    module, lesson, quiz = make_module(required=True, content="Содержательная инструкция. " * 20)
    old_questions = list(db.scalars(select(Question.id).where(Question.quiz_id == quiz.id)))
    fn = jobs.regenerate_module_quizzes_job if kind == "module" else jobs.regenerate_submodule_quiz_job
    with pytest.raises(RuntimeError, match="автопубликация"):
        fn(module_id=str(module.id), submodule_id=str(lesson.id), only_missing=False)
    db.expire_all()
    assert db.get(Submodule, lesson.id).quiz_id == quiz.id
    assert list(db.scalars(select(Question.id).where(Question.quiz_id == quiz.id))) == old_questions
    assert db.get(Module, module.id).content_revision == 1


def test_source_presigns_never_reuse_filename_metadata(client, admin_headers, monkeypatch):
    from app.routers import admin
    monkeypatch.setattr(admin, "presign_put", lambda **kwargs: "https://storage.test/put")
    monkeypatch.setattr(admin, "multipart_create", lambda **kwargs: uuid.uuid4().hex)
    payload = {"filename": "same.zip", "size_bytes": 128, "last_modified_ms": 1}
    for route in ["presign-import-zip", "multipart-import-create"]:
        first = client.post(f"/admin/modules/{route}", headers=admin_headers, json=payload)
        second = client.post(f"/admin/modules/{route}", headers=admin_headers, json=payload)
        assert first.status_code == second.status_code == 200, (first.text, second.text)
        assert first.json()["object_key"] != second.json()["object_key"]
        assert first.json()["object_key"].startswith("uploads/sources/")
        assert not first.json()["reused"] and not second.json()["reused"]


def test_historical_object_cannot_be_overwritten(client, db, admin_headers, make_module):
    module, _, _ = make_module()
    asset = ContentAsset(module_id=module.id, bucket="testing", object_key="current.csv", original_filename="table.csv", version=2)
    db.add(asset)
    db.flush()
    db.add(AssetRevision(asset_id=asset.id, version=1, bucket="testing", object_key="original.csv", original_filename="table.csv"))
    db.commit()
    response = client.post("/assets/presign-upload", headers=admin_headers,
                           json={"object_key": "original.csv", "original_filename": "overwrite.csv"})
    assert response.status_code == 409


def test_worker_records_source_and_truncates_partial_download(db, make_module, storage, redis_memory, monkeypatch):
    import hashlib
    import rq
    from app.services import module_import_jobs as jobs
    module, _, _ = make_module()
    source = "uploads/sources/test/source.zip"
    contents = zip_bytes()
    storage.objects[source] = contents
    def partial_download(bucket, key, destination, **kwargs):
        destination.write(b"partial transfer")
        raise IOError("Interrupted managed transfer")
    storage.download_fileobj = partial_download
    job = Job(JobStatus.STARTED, module_id=str(module.id), import_object_key=source)
    monkeypatch.setattr(jobs, "get_current_job", lambda: job)
    monkeypatch.setattr(rq, "get_current_job", lambda: job)
    result = jobs.import_module_zip_job(s3_object_key=source, module_id=str(module.id), expected_revision=1, reimport_existing=True)
    assert result["ok"]
    db.expire_all()
    assert db.get(Module, module.id).import_object_key == source
    assert redis_memory.get(f"admin:import_zip_sha256_by_module_id:{module.id}") == hashlib.sha256(contents).hexdigest()
    assert storage.objects[source] == contents


def test_cancel_after_commit_reports_applied_not_rolled_back(db, make_module, storage, monkeypatch):
    from app.services import module_import_jobs as jobs
    module, _, _ = make_module()
    source = "uploads/sources/test/source.zip"
    storage.objects[source] = zip_bytes()
    def cancel_at_commit(**kwargs):
        if kwargs.get("stage") == "post_commit":
            raise jobs.ImportCanceledError("too late")
    monkeypatch.setattr(jobs, "_cancel_checkpoint", cancel_at_commit)
    result = jobs.import_module_zip_job(s3_object_key=source, module_id=str(module.id), expected_revision=1, reimport_existing=True)
    assert result["ok"] and result["cancel_too_late"]
    db.expire_all()
    assert db.get(Module, module.id).content_revision == 2
    assert db.get(Module, module.id).import_object_key == source
    assert source in storage.objects and not storage.deleted


def test_uncertain_commit_never_deletes_published_objects(db, make_module, storage, monkeypatch):
    import rq
    from app.services import module_import_jobs as jobs, module_importer as importer
    module, _, _ = make_module()
    source = "uploads/sources/test/uncertain.zip"
    storage.objects[source] = zip_bytes()
    job = Job(JobStatus.STARTED, module_id=str(module.id), import_object_key=source)
    monkeypatch.setattr(jobs, "get_current_job", lambda: job)
    monkeypatch.setattr(rq, "get_current_job", lambda: job)
    monkeypatch.setattr(importer, "get_current_job", lambda: job)
    def uncertain_session():
        session = SessionLocal()
        commit = session.commit
        def lose_acknowledgement():
            commit()
            raise RuntimeError("commit acknowledged by database but response lost")
        session.commit = lose_acknowledgement
        return session
    monkeypatch.setattr(jobs, "SessionLocal", uncertain_session)
    with pytest.raises(RuntimeError, match="response lost"):
        jobs.import_module_zip_job(s3_object_key=source, module_id=str(module.id), expected_revision=1, reimport_existing=True)
    db.expire_all()
    assert db.get(Module, module.id).content_revision == 2
    assets = db.scalars(select(ContentAsset).where(ContentAsset.module_id == module.id)).all()
    assert assets and job.meta.get("uploaded_keys")
    assert all(asset.object_key in storage.objects for asset in assets)
    assert not storage.deleted


def test_reserved_general_folder_is_not_unwrapped_as_lessons(db, make_module, storage):
    from app.services.module_import_jobs import import_module_zip_job
    from app.models.submodule_asset import SubmoduleAssetMap
    module, _, _ = make_module()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("_module/general.txt", "Общие материалы")
    source = "uploads/sources/test/general.zip"
    storage.objects[source] = stream.getvalue()
    result = import_module_zip_job(s3_object_key=source, module_id=str(module.id), expected_revision=1, reimport_existing=True)
    assert result["ok"] and result["report"]["lessons_added"] == 0
    asset = db.scalar(select(ContentAsset).where(ContentAsset.module_id == module.id))
    assert asset and asset.original_filename == "general.txt"
    assert db.scalar(select(SubmoduleAssetMap).where(SubmoduleAssetMap.asset_id == asset.id)) is None


def test_requeued_old_job_never_cleans_a_previous_execution(db, make_module, storage, monkeypatch):
    from app.services import module_import_jobs as jobs
    module, _, _ = make_module()
    module.content_revision = 2
    db.add(ContentAsset(module_id=module.id, bucket="testing", object_key="live.csv", original_filename="live.csv"))
    db.commit()
    source = "uploads/sources/test/old-job.zip"
    storage.objects[source] = zip_bytes()
    storage.objects["live.csv"] = b"published material"
    job = Job(JobStatus.STARTED, module_id=str(module.id), uploaded_keys=["live.csv"], upload_attempt_id="old-attempt")
    monkeypatch.setattr(jobs, "get_current_job", lambda: job)
    with pytest.raises(ValueError, match="Модуль изменён"):
        jobs.import_module_zip_job(s3_object_key=source, module_id=str(module.id), expected_revision=1, reimport_existing=True)
    assert storage.objects["live.csv"] == b"published material" and "live.csv" not in storage.deleted
