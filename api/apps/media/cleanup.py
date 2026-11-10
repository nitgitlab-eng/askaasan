"""Delete lesson-image and lecture files nobody can reach any more.

Kept: any file with a MediaAsset row (a creator's "My images" library), and any file referenced by a lesson
(markdown) or an activity (payload/source) — including courses kept for other learners after their author
deleted their account. Removed: files with no row AND no reference, older than a day (upload grace period)."""

import re
import time

from django.conf import settings
from django.core.files.storage import default_storage

NAME = re.compile(r"/api/media/([0-9a-f]{32}\.(?:webp|png|jpg))")
LECTURE_FILE = re.compile(r"[0-9a-f]{32}\.(?:mp4|webm|m4a|mp3|wav|ogg)")
GRACE_SECONDS = 24 * 3600


def referenced_names() -> set[str]:
    from apps.learning.models import Activity, Subsection

    names: set[str] = set()
    for md in (
        Subsection.objects.exclude(explanation_md="").values_list("explanation_md", flat=True).iterator()
    ):
        names.update(NAME.findall(md))
    for payload, source in Activity.objects.values_list("payload", "source").iterator():
        names.update(NAME.findall(str(payload)))
        names.update(NAME.findall(str(source or "")))
    from apps.credentials.models import CertificateTemplate

    for logo, signature in CertificateTemplate.objects.values_list("logo", "signature"):
        names.update(NAME.findall(f"{logo} {signature}"))  # certificate logos/signatures stay
    return names


def sweep(dry_run: bool = False) -> dict:
    from .models import MediaAsset

    try:
        _, files = default_storage.listdir("aasan")
    except FileNotFoundError:
        return {"checked": 0, "deleted": 0}
    owned = set(MediaAsset.objects.values_list("name", flat=True))
    used = referenced_names()
    now, deleted = time.time(), []
    for f in files:
        if f in owned or f in used or not NAME.fullmatch(f"/api/media/{f}"):
            continue
        path = f"aasan/{f}"
        try:
            age = now - default_storage.get_modified_time(path).timestamp()
        except (OSError, NotImplementedError):
            continue
        if age < GRACE_SECONDS:
            continue
        if not dry_run:
            default_storage.delete(path)
        deleted.append(f)
    return {
        "checked": len(files),
        "deleted": len(deleted),
        "files": deleted[:20],
        "root": str(settings.MEDIA_ROOT),
    }


def lecture_referenced(path: str) -> bool:
    """Is lectures/<uid>/<name> still used by a lesson (a video activity built from it, or lesson markdown)? Courses kept
    for other learners after their author left keep working; everything else may go."""
    from django.db.models import Q, TextField
    from django.db.models.functions import Cast

    from apps.learning.models import Activity, Subsection

    if Subsection.objects.filter(explanation_md__contains=path).exists():
        return True
    return (
        Activity.objects.annotate(p=Cast("payload", TextField()), s=Cast("source", TextField()))
        .filter(Q(p__contains=path) | Q(s__contains=path))
        .exists()
    )


def delete_lecture_if_unused(path: str) -> bool:
    """Remove a lecture file once no LectureVideo row owns it and no lesson references it."""
    from apps.studio.models import LectureVideo

    if not path or LectureVideo.objects.filter(file=path).exists() or lecture_referenced(path):
        return False
    try:
        if default_storage.exists(path):
            default_storage.delete(path)
            return True
    except OSError:
        pass
    return False


def sweep_lectures(dry_run: bool = False) -> dict:
    """Lecture files left behind before rows cleaned up after themselves (older than the upload grace period)."""
    from apps.studio.models import LectureVideo

    try:
        dirs, _ = default_storage.listdir("lectures")
    except FileNotFoundError:
        return {"checked": 0, "deleted": 0}
    owned = set(LectureVideo.objects.exclude(file="").values_list("file", flat=True))
    now, checked, deleted = time.time(), 0, []
    for d in dirs:
        if not d.isdigit():
            continue
        for f in default_storage.listdir(f"lectures/{d}")[1]:
            checked += 1
            path = f"lectures/{d}/{f}"
            if path in owned or not LECTURE_FILE.fullmatch(f):
                continue
            try:
                if now - default_storage.get_modified_time(path).timestamp() < GRACE_SECONDS:
                    continue
            except (OSError, NotImplementedError):
                continue
            if lecture_referenced(path):
                continue
            if not dry_run:
                default_storage.delete(path)
            deleted.append(path)
    return {"checked": checked, "deleted": len(deleted), "files": deleted[:20]}
