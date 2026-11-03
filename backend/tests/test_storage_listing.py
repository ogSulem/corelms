"""Параметр limit у списка объектов S3 должен работать.

Раньше ручка «выбрать уже загруженный ZIP» игнорировала limit и вытягивала до
1000 ключей с несколькими страницами — экран открывался секундами.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services import storage


class _FakeS3:
    def __init__(self, total: int = 1000) -> None:
        self.calls: list[int] = []
        self.total = total

    def list_objects_v2(self, Bucket, Prefix, MaxKeys, ContinuationToken=None):  # noqa: N803
        self.calls.append(int(MaxKeys))
        return {
            "Contents": [
                {"Key": f"{Prefix}file-{i:04d}.zip", "Size": 10, "LastModified": datetime(2026, 1, 1, tzinfo=timezone.utc),
                 "ETag": '"etag"'}
                for i in range(self.total)
            ],
            "IsTruncated": False,
        }


def test_limit_is_honoured_and_scan_is_bounded(monkeypatch):
    fake = _FakeS3()
    monkeypatch.setattr(storage, "_runtime_s3", lambda: {})
    monkeypatch.setattr(storage, "ensure_bucket_exists", lambda: None)
    monkeypatch.setattr(storage, "get_s3_client", lambda: fake)

    items = storage.s3_list_objects(prefix="uploads/", limit=5, suffix=".zip")
    assert len(items) == 5, f"limit=5, вернулось {len(items)}"
    assert len(fake.calls) == 1, f"лишние страницы: {fake.calls}"

    many = storage.s3_list_objects(prefix="uploads/", limit=150, suffix=".zip")
    assert len(many) == 150
