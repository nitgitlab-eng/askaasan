"""P4: Rhythm planner — daily study blocks from the plan, skip/re-plan, move, pauses (away mode), study buddies."""

import re
from datetime import date, timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import StudyBlock, StudyBuddy, StudyPause

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MAX_PAUSE_DAYS = 60


# ── Pauses ───────────────────────────────────────────────────────────


def paused_on(user_id: int, day: date) -> bool:
    return StudyPause.objects.filter(user_id=user_id, start__lte=day, end__gte=day).exists()


def all_paused(user_id: int, start: date, end: date) -> bool:
    """True if every day in [start, end] is inside a pause (empty range → True)."""
    if start > end:
        return True
    covered = set()
    for p in StudyPause.objects.filter(user_id=user_id, start__lte=end, end__gte=start):
        d = max(p.start, start)
        while d <= min(p.end, end):
            covered.add(d)
            d += timedelta(days=1)
    return len(covered) == (end - start).days + 1


# ── Blocks ───────────────────────────────────────────────────────────


def _prefs(user):
    from apps.accounts.preferences import upgrade

    return upgrade(user.preferences.data)["learning"]


def _add_minutes(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(":"))
    t = min(23 * 60 + 59, h * 60 + m + minutes)
    return f"{t // 60:02d}:{t % 60:02d}"


def _content(user, n: int) -> list[dict]:
    """What to study in the main block each day: in-progress lesson first, then recommendations."""
    from apps.paths.services import recommend

    items = []
    for r in recommend(user, limit=8):
        if r["kind"] in ("continue", "next", "practice", "start", "path"):
            items.append(
                {
                    "kind": "practice" if r["kind"] == "practice" else "lesson",
                    "title": r["title"],
                    "link": r["link"],
                }
            )
    if not items:
        items = [{"kind": "lesson", "title": "", "link": "/learn"}]
    return [items[i % len(items)] for i in range(n)]


def ensure_blocks(user, start: date, days: int = 7) -> None:
    """Generate blocks for planned study days in [start, start+days) from today on (idempotent per day)."""
    p = _prefs(user)
    today = timezone.localdate()
    when = (p["reminder_times"] or ["19:00"])[0]
    goal = p["daily_goal_minutes"]
    targets = [start + timedelta(days=i) for i in range(days)]
    targets = _unplanned(user, [d for d in targets if d >= today and d.weekday() in p["study_days"]])
    if not targets:
        return
    content = _content(user, len(targets))  # outside the lock: it reads recommendations, never blocks
    with transaction.atomic():
        # Serialise per learner and re-check, so two concurrent GETs can't both fill the same day.
        type(user).objects.select_for_update().filter(pk=user.pk).first()
        still = set(_unplanned(user, targets))
        _create_blocks(
            user, [(d, c) for d, c in zip(targets, content, strict=True) if d in still], when, goal
        )


def _unplanned(user, days: list[date]) -> list[date]:
    have = set(StudyBlock.objects.filter(user=user, date__in=days, auto=True).values_list("date", flat=True))
    # A day whose planner block was moved elsewhere is already planned; don't refill it.
    have |= set(
        StudyBlock.objects.filter(user=user, moved_from__in=days)
        .exclude(kind="custom")
        .values_list("moved_from", flat=True)
    )
    return [d for d in days if d not in have and not paused_on(user.id, d)]


def _create_blocks(user, todo, when, goal) -> None:
    rows = []
    for d, c in todo:
        review_min = 5 if goal >= 15 else 0
        if review_min:
            rows.append(
                StudyBlock(
                    user=user, date=d, start=when, minutes=review_min, kind="today", title="", link="/today"
                )
            )
        rows.append(
            StudyBlock(
                user=user,
                date=d,
                start=_add_minutes(when, review_min),
                minutes=max(5, goal - review_min),
                **c,
            )
        )
    StudyBlock.objects.bulk_create(rows)


def _next_free_day(user, after: date) -> date | None:
    p = _prefs(user)
    d = max(after, timezone.localdate() - timedelta(days=1))
    for _ in range(21):
        d += timedelta(days=1)
        if d.weekday() in p["study_days"] and not paused_on(user.id, d):
            return d
    return None


def _block_out(b: StudyBlock, xp_days: set, today: date) -> dict:
    state = b.status
    if state == "planned" and b.date < today:
        state = "done" if b.date in xp_days else "missed"
    return {
        "id": b.id,
        "date": b.date,
        "start": b.start,
        "minutes": b.minutes,
        "kind": b.kind,
        "title": b.title,
        "link": b.link,
        "status": b.status,
        "state": state,
        "moved_from": b.moved_from,
        "auto": b.auto,
    }


def week_blocks(user, start: date) -> dict:
    from apps.game.models import XPEvent

    ensure_blocks(user, start)
    end = start + timedelta(days=6)
    today = timezone.localdate()
    xp_days = set(
        XPEvent.objects.filter(user=user, day__gte=start, day__lte=end, xp__gt=0).values_list(
            "day", flat=True
        )
    )
    blocks = [
        _block_out(b, xp_days, today)
        for b in StudyBlock.objects.filter(user=user, date__gte=start, date__lte=end)
    ]
    pauses = [
        {"id": p.id, "start": p.start, "end": p.end, "reason": p.reason}
        for p in StudyPause.objects.filter(user=user, end__gte=today - timedelta(days=30))
    ]
    days = []
    for i in range(7):
        d = start + timedelta(days=i)
        days.append(
            {"day": d, "paused": any(p["start"] <= d <= p["end"] for p in pauses), "studied": d in xp_days}
        )
    return {"start": start, "days": days, "blocks": blocks, "pauses": pauses}


def _week_start_param(request) -> date:
    from apps.game.services import week_start

    raw = request.query_params.get("week")
    try:
        d = date.fromisoformat(raw) if raw else timezone.localdate()
    except ValueError:
        d = timezone.localdate()
    return week_start(d)


@api_view(["GET", "POST"])
def blocks(request):
    """GET ?week=YYYY-MM-DD → that week's blocks. POST {date, start, minutes, title} → add a custom block."""
    if request.method == "POST":
        ser = BlockIn(data=request.data)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data
        if StudyBlock.objects.filter(user=request.user, date__gte=timezone.localdate()).count() >= 200:
            return Response({"code": "too_many_blocks"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        StudyBlock.objects.create(
            user=request.user,
            date=v["date"],
            start=v["start"],
            minutes=v["minutes"],
            kind="custom",
            title=v["title"],
            link="",
            auto=False,
        )
        return Response(week_blocks(request.user, _ws(v["date"])), status=status.HTTP_201_CREATED)
    return Response(week_blocks(request.user, _week_start_param(request)))


def _ws(d):
    from apps.game.services import week_start

    return week_start(d)


class BlockIn(serializers.Serializer):
    date = serializers.DateField()
    start = serializers.RegexField(HHMM)
    minutes = serializers.IntegerField(min_value=5, max_value=240, default=15)
    title = serializers.CharField(max_length=200)

    def validate_date(self, d):
        today = timezone.localdate()
        if not today - timedelta(days=1) <= d <= today + timedelta(days=90):
            raise serializers.ValidationError("out_of_range")
        return d


class BlockAction(serializers.Serializer):
    action = serializers.ChoiceField(choices=["skip", "done", "undo", "move", "delete"])
    date = serializers.DateField(required=False)
    start = serializers.RegexField(HHMM, required=False)


@api_view(["POST"])
def block_action(request, pk):
    """skip → re-plan onto the next free study day · done · undo · move {date,start} · delete (custom blocks only)."""
    b = get_object_or_404(StudyBlock, pk=pk, user=request.user)
    ser = BlockAction(data=request.data)
    ser.is_valid(raise_exception=True)
    v = ser.validated_data
    a = v["action"]
    today = timezone.localdate()
    moved_to = None
    with transaction.atomic():
        if a == "skip":
            if b.status != "planned":
                return Response({"code": "not_planned"}, status=status.HTTP_400_BAD_REQUEST)
            b.status = "skipped"
            b.save(update_fields=["status"])
            nd = _next_free_day(request.user, max(b.date, today))
            if nd and b.kind != "today":  # the daily revision recurs anyway
                last = (
                    StudyBlock.objects.filter(user=request.user, date=nd)
                    .exclude(status="skipped")
                    .order_by("-start")
                    .first()
                )
                start = _add_minutes(last.start, last.minutes) if last else b.start
                nb = StudyBlock.objects.create(
                    user=request.user,
                    date=nd,
                    start=start,
                    minutes=b.minutes,
                    kind=b.kind,
                    title=b.title,
                    link=b.link,
                    moved_from=b.date,
                    auto=False,
                )
                moved_to = nb.date
        elif a == "done":
            b.status = "done"
            b.save(update_fields=["status"])
        elif a == "undo":
            b.status = "planned"
            b.save(update_fields=["status"])
        elif a == "move":
            d, s = v.get("date") or b.date, v.get("start") or b.start
            if not today - timedelta(days=1) <= d <= today + timedelta(days=90):
                return Response({"code": "out_of_range"}, status=status.HTTP_400_BAD_REQUEST)
            if d != b.date:
                if not b.moved_from:
                    b.moved_from = b.date
                b.auto = False  # now the learner's own block: its old day stays planned, its new day still gets its own
            b.date, b.start, b.status = d, s, "planned"
            b.save()
        elif a == "delete":
            if b.auto:
                return Response({"code": "skip_instead"}, status=status.HTTP_400_BAD_REQUEST)
            b.delete()
    out = week_blocks(request.user, _ws(v.get("date") or b.date))  # b.date is still set after delete
    return Response({**out, "moved_to": moved_to})


# ── Pause / away mode ────────────────────────────────────────────────


class PauseIn(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    reason = serializers.ChoiceField(choices=["away", "exams", "festival", "sick", "other"], default="away")

    def validate(self, v):
        today = timezone.localdate()
        if v["end"] < v["start"]:
            raise serializers.ValidationError({"end": "before_start"})
        if v["start"] < today - timedelta(days=1):
            raise serializers.ValidationError({"start": "in_past"})
        if (v["end"] - v["start"]).days + 1 > MAX_PAUSE_DAYS:
            raise serializers.ValidationError({"end": "too_long"})
        return v


@api_view(["GET", "POST"])
def pauses(request):
    if request.method == "POST":
        ser = PauseIn(data=request.data)
        ser.is_valid(raise_exception=True)
        if StudyPause.objects.filter(user=request.user, end__gte=timezone.localdate()).count() >= 5:
            return Response({"code": "too_many_pauses"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        p = StudyPause.objects.create(user=request.user, **ser.validated_data)
        # Planned auto blocks inside the pause are cleared (they'd only nag).
        StudyBlock.objects.filter(
            user=request.user, auto=True, status="planned", date__gte=p.start, date__lte=p.end
        ).delete()
    today = timezone.localdate()
    return Response(
        [
            {
                "id": p.id,
                "start": p.start,
                "end": p.end,
                "reason": p.reason,
                "active": p.start <= today <= p.end,
            }
            for p in StudyPause.objects.filter(user=request.user, end__gte=today)
        ]
    )


@api_view(["DELETE"])
def pause_detail(request, pk):
    get_object_or_404(StudyPause, pk=pk, user=request.user).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# ── Study buddies ────────────────────────────────────────────────────


def _name(u) -> str:
    return (u.profile.display_name or u.email.split("@")[0])[:40]


def _buddy_summaries(users) -> dict:
    """{user_id: summary} for several buddies in a fixed number of queries (no per-buddy N+1)."""
    from django.db.models import Count, Q

    from apps.game.models import PlayerStats, XPEvent
    from apps.game.services import week_start

    ids = [u.id for u in users]
    start, today = week_start(), timezone.localdate()
    stats = {s.user_id: s for s in PlayerStats.objects.filter(user_id__in=ids)}
    blocks = {
        r["user_id"]: r
        for r in StudyBlock.objects.filter(
            user_id__in=ids, date__gte=start, date__lte=start + timedelta(days=6)
        )
        .exclude(status="skipped")
        .values("user_id")
        .annotate(planned=Count("id"), done=Count("id", filter=Q(status="done")))
    }
    studied: dict[int, set] = {}
    for uid, d in XPEvent.objects.filter(user_id__in=ids, day__gte=start, xp__gt=0).values_list(
        "user_id", "day"
    ):
        studied.setdefault(uid, set()).add(d.isoformat())
    paused = set(
        StudyPause.objects.filter(user_id__in=ids, start__lte=today, end__gte=today).values_list(
            "user_id", flat=True
        )
    )
    out = {}
    for u in users:
        s, b = stats.get(u.id), blocks.get(u.id, {})
        out[u.id] = {
            "name": _name(u),
            "streak": s.streak if s else 0,
            "last_active": s.last_active if s else None,
            "planned": b.get("planned", 0),
            "done": b.get("done", 0),
            "studied_days": sorted(studied.get(u.id, ())),
            "paused": u.id in paused,
        }
    return out


@api_view(["GET", "POST"])
def buddies(request):
    """GET: accepted buddies (both directions) + my pending invites. POST: create an invite link to share."""
    from django.db.models import Q

    if request.method == "POST":
        if StudyBuddy.objects.filter(inviter=request.user, accepted_at__isnull=True).count() >= 10:
            return Response({"code": "too_many_invites"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        StudyBuddy.objects.create(inviter=request.user)
    from django.conf import settings

    pairs = [
        (b.id, b.buddy if b.inviter_id == request.user.id else b.inviter)
        for b in StudyBuddy.objects.filter(
            Q(inviter=request.user) | Q(buddy=request.user), accepted_at__isnull=False
        ).select_related("inviter__profile", "buddy__profile")
    ]
    summaries = _buddy_summaries([other for _, other in pairs])
    rows = [{"id": bid, **summaries[other.id]} for bid, other in pairs]
    pending = [
        {"id": b.id, "link": f"{settings.FRONTEND_URL}/buddy/{b.token}", "created_at": b.created_at}
        for b in StudyBuddy.objects.filter(inviter=request.user, accepted_at__isnull=True).order_by(
            "-created_at"
        )
    ]
    return Response(
        {"buddies": rows, "pending": pending},
        status=status.HTTP_201_CREATED if request.method == "POST" else 200,
    )


@api_view(["GET", "POST"])
def buddy_accept(request, token):
    b = StudyBuddy.objects.filter(token=token).select_related("inviter__profile").first()
    if not b:
        return Response({"code": "invalid_invite"}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "GET":
        return Response(
            {
                "inviter": _name(b.inviter),
                "accepted": bool(b.accepted_at),
                "self": b.inviter_id == request.user.id,
            }
        )
    if b.inviter_id == request.user.id:
        return Response({"code": "own_invite"}, status=status.HTTP_400_BAD_REQUEST)
    if b.accepted_at:
        if b.buddy_id == request.user.id:
            return Response({"ok": True})
        return Response({"code": "invite_used"}, status=status.HTTP_409_CONFLICT)
    from django.db.models import Q

    if StudyBuddy.objects.filter(
        Q(inviter=b.inviter, buddy=request.user) | Q(inviter=request.user, buddy=b.inviter),
        accepted_at__isnull=False,
    ).exists():
        b.delete()
        return Response({"ok": True})
    b.buddy, b.accepted_at = request.user, timezone.now()
    b.save()
    from apps.game.services import notify

    notify(b.inviter, "buddy", f"🤝 {_name(request.user)} is now your study buddy", link="/plan")
    return Response({"ok": True})


@api_view(["DELETE"])
def buddy_detail(request, pk):
    from django.db.models import Q

    get_object_or_404(StudyBuddy, Q(inviter=request.user) | Q(buddy=request.user), pk=pk).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
