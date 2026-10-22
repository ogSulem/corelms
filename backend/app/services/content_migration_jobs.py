"""Compatibility entry point for obsolete, already-enqueued migration jobs."""
from __future__ import annotations


def migrate_legacy_submodule_content_job(*, limit: int = 200) -> dict:
    # Text now lives in the transactional lesson record. Positional S3 keys can
    # overwrite existing material after reordering; never run the old migrator.
    return {"ok": True, "migrated": 0, "errors": 0, "remaining_count": 0, "finished": True,
            "skipped": "deprecated: edit lesson content in the module editor"}
