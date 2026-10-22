"""Preserve old RQ import paths without permitting replacement of originals.

Browser copies are made by services.media; old bulk writer jobs must not resume.
"""


class TranscodeCanceledError(RuntimeError):
    """Kept for callers serialized before the original-preserving pipeline."""


def transcode_all_videos_job(*args, **kwargs):
    raise RuntimeError("Старая пакетная замена видео отключена. Откройте файлы: отдельный media-worker создаст браузерные копии без изменения оригиналов.")
