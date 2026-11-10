"""Undo/redo + named versions for authored courses, built on full snapshots.

`history_pos` on the course is the seq of the revision the course currently matches. Recording after an
undo discards the redo branch (auto revisions only — named versions are kept). At most MAX_AUTO auto revisions."""

from django.db import transaction
from django.db.models import Max

from apps.learning.models import Curriculum

from . import snapshot
from .models import CourseRevision

MAX_AUTO = 60


def _next_seq(cur) -> int:
    return (CourseRevision.objects.filter(curriculum=cur).aggregate(m=Max("seq"))["m"] or 0) + 1


@transaction.atomic
def record(cur: Curriculum, label: str = "", user=None, pinned: bool = False) -> CourseRevision:
    cur = Curriculum.objects.select_for_update().get(pk=cur.pk)
    CourseRevision.objects.filter(
        curriculum=cur, seq__gt=cur.history_pos, pinned=False
    ).delete()  # drop redo branch
    rev = CourseRevision.objects.create(
        curriculum=cur,
        seq=_next_seq(cur),
        label=label[:120],
        data=snapshot.serialize(cur),
        pinned=pinned,
        created_by=user,
    )
    Curriculum.objects.filter(pk=cur.pk).update(history_pos=rev.seq)
    old = (
        CourseRevision.objects.filter(curriculum=cur, pinned=False)
        .order_by("-seq")
        .values_list("id", flat=True)[MAX_AUTO:]
    )
    CourseRevision.objects.filter(id__in=list(old)).delete()
    return rev


def ensure_baseline(cur: Curriculum, user=None) -> None:
    """The first edit must be undoable: keep a snapshot of the course as it was when the editor opened."""
    if cur.status == "ready" and not CourseRevision.objects.filter(curriculum=cur).exists():
        record(cur, "Start", user)


def state(cur: Curriculum) -> dict:
    cur.refresh_from_db(fields=["history_pos"])
    revs = CourseRevision.objects.filter(curriculum=cur)
    prev = revs.filter(seq__lt=cur.history_pos, pinned=False).order_by("-seq").first()
    nxt = revs.filter(seq__gt=cur.history_pos, pinned=False).order_by("seq").first()
    return {
        "can_undo": bool(prev),
        "can_redo": bool(nxt),
        "undo_label": _label_at(cur, cur.history_pos),
        "redo_label": nxt.label if nxt else "",
    }


def _label_at(cur, seq) -> str:
    r = CourseRevision.objects.filter(curriculum=cur, seq=seq).first()
    return r.label if r else ""


@transaction.atomic
def step(cur: Curriculum, direction: int) -> bool:
    """direction -1 = undo, +1 = redo. Returns False if there's nothing to do."""
    cur = Curriculum.objects.select_for_update().get(pk=cur.pk)
    revs = CourseRevision.objects.filter(curriculum=cur, pinned=False)
    target = (
        revs.filter(seq__lt=cur.history_pos).order_by("-seq")
        if direction < 0
        else revs.filter(seq__gt=cur.history_pos).order_by("seq")
    ).first()
    if not target:
        return False
    snapshot.apply(cur, target.data, trusted=True)
    Curriculum.objects.filter(pk=cur.pk).update(history_pos=target.seq)
    return True


def versions(cur: Curriculum) -> list[dict]:
    return [
        {
            "id": r.id,
            "label": r.label,
            "created_at": r.created_at,
            "lessons": sum(len(s["lessons"]) for s in r.data.get("sections", [])),
        }
        for r in CourseRevision.objects.filter(curriculum=cur, pinned=True).order_by("-created_at")[:30]
    ]


@transaction.atomic
def restore(cur: Curriculum, rev: CourseRevision, user=None) -> None:
    snapshot.apply(cur, rev.data, trusted=True)
    record(cur, f"Restored “{rev.label}”"[:120], user)


@transaction.atomic
def save_version(cur: Curriculum, label: str, user=None) -> CourseRevision:
    """A named version: a pinned snapshot that doesn't move the undo pointer."""
    cur = Curriculum.objects.select_for_update().get(pk=cur.pk)
    return CourseRevision.objects.create(
        curriculum=cur,
        seq=_next_seq(cur),
        label=label[:120] or "Version",
        data=snapshot.serialize(cur),
        pinned=True,
        created_by=user,
    )
