from datetime import UTC, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from apps.accounts.preferences import upgrade
from apps.learning.models import UserSubsectionState
from apps.review.models import ReviewLog

from .catalog import (
    BADGES,
    FREE_ITEMS,
    ITEMS,
    MAX_FREEZES,
    STREAK_FREEZE_PRICE,
    league_for,
    level_for,
    xp_for_level,
)
from .models import Notification, PlayerStats, UserBadge, XPEvent
from .services import (
    RepairError,
    award,
    daily_goal_xp,
    detect_break,
    grant_badge,
    nudges,
    repair_offer,
    repair_streak,
    stats_for,
    streak_alive,
    week_start,
    weekly_xp,
)


def _status(user):
    s = detect_break(user)  # records a streak the calendar already ended, so the repair offer shows now
    lvl = level_for(s.xp)
    today = timezone.localdate()
    today_xp = XPEvent.objects.filter(user=user, day=today).aggregate(t=Sum("xp"))["t"] or 0
    # A streak is only "alive" if you were active today or yesterday (or a freeze can bridge, or away mode).
    gap = (today - s.last_active).days if s.last_active else None
    alive = streak_alive(s, today)
    week = weekly_xp(user)
    from apps.orgs.extras import blocked

    repair = repair_offer(s, today)
    if repair:
        repair["coins_ok"] = not blocked(user, "shop")
    return {
        "xp": s.xp,
        "coins": s.coins,
        "level": lvl,
        "level_floor": xp_for_level(lvl),
        "level_next": xp_for_level(lvl + 1),
        "streak": s.streak if alive else 0,
        "best_streak": s.best_streak,
        "active_today": gap == 0,
        "freezes": s.freezes,
        "today_xp": today_xp,
        "daily_goal_xp": daily_goal_xp(user),
        "weekly_xp": week,
        "league": league_for(week),
        "owned_items": sorted(FREE_ITEMS | set(s.owned_items)),
        "referral_code": s.referral_code,
        "show_on_leaderboard": s.show_on_leaderboard,
        "unread": Notification.objects.filter(user=user, read=False).count(),
        "repair": repair,
    }


@api_view(["GET"])
def game_status(request):
    return Response(_status(request.user))


@api_view(["GET"])
def achievements(request):
    lang = "ta" if request.user.profile.language == "ta" else "en"
    earned = {b.code: b.earned_at for b in UserBadge.objects.filter(user=request.user)}
    days = [timezone.localdate() - timedelta(days=i) for i in range(27, -1, -1)]
    per_day = dict(
        XPEvent.objects.filter(user=request.user, day__gte=days[0]).values_list("day").annotate(t=Sum("xp"))
    )
    return Response(
        {
            "badges": [
                {
                    "code": c,
                    "icon": b["icon"],
                    "name": b[lang],
                    "desc": b[f"desc_{lang}"],
                    "earned_at": earned.get(c),
                }
                for c, b in BADGES.items()
            ],
            "calendar": [{"day": d, "xp": per_day.get(d, 0)} for d in days],
            "lessons_completed": UserSubsectionState.objects.filter(
                user=request.user, status=UserSubsectionState.Status.COMPLETED
            ).count(),
        }
    )


@api_view(["GET"])
def shop(request):
    lang = "ta" if request.user.profile.language == "ta" else "en"
    s = stats_for(request.user)
    lvl = level_for(s.xp)
    owned = FREE_ITEMS | set(s.owned_items)
    return Response(
        {
            "coins": s.coins,
            "level": lvl,
            "items": [
                {
                    "code": c,
                    "slot": i["slot"],
                    "name": i[lang],
                    "price": i["price"],
                    "level": i["level"],
                    "owned": c in owned,
                    "locked": lvl < i["level"],
                }
                for c, i in ITEMS.items()
            ],
            "freeze": {"price": STREAK_FREEZE_PRICE, "owned": s.freezes, "max": MAX_FREEZES},
        }
    )


@api_view(["POST"])
@transaction.atomic
def buy(request):
    from apps.orgs.extras import blocked, feature_off_response

    if blocked(request.user, "shop"):
        return feature_off_response("shop")
    code = request.data.get("item")
    s = PlayerStats.objects.select_for_update().get_or_create(user=request.user)[0]
    if code == "streak_freeze":
        if s.freezes >= MAX_FREEZES:
            return Response({"code": "max_freezes"}, status=status.HTTP_400_BAD_REQUEST)
        price = STREAK_FREEZE_PRICE
    else:
        item = ITEMS.get(code)
        if not item:
            return Response({"code": "unknown_item"}, status=status.HTTP_404_NOT_FOUND)
        if code in FREE_ITEMS or code in s.owned_items:
            return Response({"code": "already_owned"}, status=status.HTTP_400_BAD_REQUEST)
        if level_for(s.xp) < item["level"]:
            return Response({"code": "level_locked"}, status=status.HTTP_403_FORBIDDEN)
        price = item["price"]
    if s.coins < price:
        return Response({"code": "not_enough_coins"}, status=status.HTTP_402_PAYMENT_REQUIRED)
    s.coins -= price
    if code == "streak_freeze":
        s.freezes += 1
    else:
        s.owned_items = [*s.owned_items, code]
    s.save()
    XPEvent.objects.create(
        user=request.user, kind="purchase", coins=-price, ref=code, day=timezone.localdate()
    )
    return Response(_status(request.user))


@api_view(["POST"])
def streak_repair(request):
    """Repair a broken streak: {"how": "coins"} (STREAK_REPAIR_PRICE coins) or {"how": "revive"} (claim a finished
    revival; it is normally granted automatically by the lesson that completes it)."""
    from apps.orgs.extras import blocked, feature_off_response

    how = request.data.get("how") if isinstance(request.data, dict) else None
    if how == "coins" and blocked(request.user, "shop"):
        return feature_off_response("shop")
    try:
        out = repair_streak(request.user, how)
    except RepairError as e:
        return Response({"code": e.code, **e.extra}, status=e.status)
    return Response({"repaired": out, "status": _status(request.user)})


def _board_events(user_ids, start):
    """This week's XP events that may appear on a board: opted-in learners, minus learners of a school that switched
    the leaderboard off; limited to `user_ids` (a queryset of ids) for an org or class board."""
    from apps.orgs.extras import hidden_from_boards

    qs = XPEvent.objects.filter(day__gte=start, user__game__show_on_leaderboard=True).exclude(
        user_id__in=hidden_from_boards()
    )
    return qs if user_ids is None else qs.filter(user_id__in=user_ids)


def board_rows(user_ids, me_id: int, limit: int = 20, start=None) -> list[dict]:
    """Weekly XP ranking among `user_ids` (None = everyone). First names only."""
    rows = (
        _board_events(user_ids, start or week_start())
        .values("user_id", "user__profile__display_name")
        .annotate(xp=Sum("xp"))
        .order_by("-xp", "user_id")[:limit]
    )
    return [
        {
            "rank": i,
            "name": (r["user__profile__display_name"] or "Learner").split()[0][
                :16
            ],  # first name only (privacy)
            "xp": r["xp"],
            "me": r["user_id"] == me_id,
            "league": league_for(r["xp"]),
        }
        for i, r in enumerate(rows, 1)
    ]


def _my_rank(user, user_ids, start, my_xp: int) -> int | None:
    """The caller's place on this board (even outside the top rows); None when they aren't on it."""
    from apps.orgs.extras import hidden_from_boards

    if not my_xp or not stats_for(user).show_on_leaderboard:
        return None
    if hidden_from_boards().filter(user_id=user.id).exists():
        return None
    if user_ids is not None and not user_ids.filter(user_id=user.id).exists():
        return None
    above = (
        _board_events(user_ids, start).values("user_id").annotate(xp=Sum("xp")).filter(xp__gt=my_xp).count()
    )
    return above + 1


def _board_scopes(user) -> list[dict]:
    """The boards this learner can open: global, each of their orgs with the leaderboard on, and their classes."""
    from apps.orgs.extras import feature_on
    from apps.orgs.models import Membership

    out = [{"scope": "global", "name": ""}]
    for m in Membership.objects.filter(user=user).select_related("org").order_by("joined_at"):
        if not feature_on(m.org, "leaderboard"):
            continue
        out.append({"scope": "org", "org": m.org.slug, "name": m.org.display_name or m.org.name})
        for g in m.groups.filter(org=m.org).exclude(name="Everyone").order_by("name"):
            out.append({"scope": "class", "org": m.org.slug, "class": g.id, "name": g.name})
    return out


def _resolve_scope(user, scope: str, org_slug: str, class_id: str):
    """→ (user ids queryset or None, display name) or a Response refusing it. Org boards need membership; class boards
    need membership of the class, or staff whose class scope includes it (teach.scope_groups)."""
    from apps.orgs.extras import feature_off_response, feature_on
    from apps.orgs.models import Group, Membership
    from apps.orgs.perms import RANK
    from apps.orgs.teach import scope_groups

    nope = Response({"code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    if scope == "org":
        m = Membership.objects.filter(user=user, org__slug=org_slug or "").select_related("org").first()
        if not m:
            return nope
        if not feature_on(m.org, "leaderboard"):
            return feature_off_response("leaderboard")
        return Membership.objects.filter(org=m.org).values("user_id"), m.org.display_name or m.org.name
    if scope == "class":
        g = (
            Group.objects.filter(pk=class_id).select_related("org").first()
            if str(class_id).isdigit()
            else None
        )
        m = g and Membership.objects.filter(user=user, org=g.org).first()
        if not g or not m or g.name == "Everyone":
            return nope
        allowed = g.members.filter(pk=m.pk).exists()
        if not allowed and RANK[m.role] >= RANK["manager"]:
            mine = scope_groups(m)
            allowed = mine is None or g.id in mine
        if not allowed:
            return nope
        if not feature_on(g.org, "leaderboard"):
            return feature_off_response("leaderboard")
        return Membership.objects.filter(groups=g).values("user_id"), g.name
    return None, ""


@api_view(["GET"])
def leaderboard(request):
    """Weekly board. ?scope=global (default) | org&org=<slug> | class&class=<id>."""
    from apps.orgs.extras import blocked, feature_off_response

    if blocked(request.user, "leaderboard"):
        return feature_off_response("leaderboard")
    scope = request.query_params.get("scope") or "global"
    if scope not in ("global", "org", "class"):
        return Response({"code": "bad_scope"}, status=status.HTTP_400_BAD_REQUEST)
    resolved = _resolve_scope(
        request.user, scope, request.query_params.get("org", ""), request.query_params.get("class", "")
    )
    if isinstance(resolved, Response):
        return resolved
    user_ids, name = resolved
    start = week_start()
    my = weekly_xp(request.user)
    rank = _my_rank(request.user, user_ids, start, my)
    return Response(
        {
            "scope": scope,
            "name": name,
            "scopes": _board_scopes(request.user),
            "week_start": start,
            "ends_in_days": 7 - timezone.localdate().weekday(),
            "rows": board_rows(user_ids, request.user.id, start=start),
            "me": {"xp": my, "league": league_for(my), "rank": rank},
            "my_rank": rank,
        }
    )


@api_view(["PATCH"])
def settings_view(request):
    s = stats_for(request.user)
    if "show_on_leaderboard" in request.data:
        try:
            s.show_on_leaderboard = serializers.BooleanField().to_internal_value(
                request.data["show_on_leaderboard"]
            )
        except serializers.ValidationError:
            return Response({"code": "bad_value"}, status=status.HTTP_400_BAD_REQUEST)
        s.save(update_fields=["show_on_leaderboard"])
    return Response(_status(request.user))


BOSS_WINDOW = timedelta(minutes=45)
BOSS_PASS = 0.7


@api_view(["POST"])
def boss_result(request, section_id):
    """Server-side verdict from the learner's own recent checkpoint answers."""

    from apps.learning.access import get_viewable_section

    section = get_viewable_section(request.user, section_id)
    logs = ReviewLog.objects.filter(
        card__user=request.user,
        card__activity__subsection__section=section,
        card__activity__kind="lesson",
        created_at__gte=timezone.now() - BOSS_WINDOW,
    )
    if logs.count() < 3:
        return Response({"code": "not_enough_answers"}, status=status.HTTP_400_BAD_REQUEST)
    latest = {}
    for log in logs.order_by("created_at"):
        latest[log.card_id] = log.score
    score = sum(latest.values()) / len(latest)
    won = score >= BOSS_PASS
    out = {"won": won, "score": round(score, 3)}
    if won:
        out["reward"] = award(request.user, "boss_win", ref=f"boss:{section.id}")
        if grant_badge(request.user, "boss_slayer"):
            out["reward"].setdefault("badges", []).append("boss_slayer")
    return Response(out)


@api_view(["GET"])
def notifications(request):
    qs = Notification.objects.filter(user=request.user)[:30]
    return Response(
        [
            {
                "id": n.id,
                "kind": n.kind,
                "title": n.title,
                "body": n.body,
                "link": n.link,
                "read": n.read,
                "created_at": n.created_at,
            }
            for n in qs
        ]
    )


@api_view(["POST"])
def notifications_read(request):
    Notification.objects.filter(user=request.user, read=False).update(read=True)
    return Response(status=status.HTTP_204_NO_CONTENT)


def _ics(user) -> str:
    prefs = upgrade(user.preferences.data)["learning"]
    days = prefs["study_days"] or list(range(7))
    times = prefs["reminder_times"] or ["19:00"]
    minutes = prefs["daily_goal_minutes"]
    byday = ",".join(["MO", "TU", "WE", "TH", "FR", "SA", "SU"][d] for d in sorted(set(days)) if 0 <= d <= 6)
    hh, mm = (times[0].split(":") + ["00"])[:2]
    start = timezone.localdate()
    stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    end_h, end_m = divmod(int(hh) * 60 + int(mm) + minutes, 60)
    end_day = start + timedelta(days=end_h // 24)  # a late reminder can end after midnight
    from apps.study.models import StudyBlock
    from apps.study.planner import ensure_blocks

    ensure_blocks(user, start, days=14)
    blocks = list(
        StudyBlock.objects.filter(
            user=user, date__gte=start, date__lte=start + timedelta(days=13), status="planned"
        )
    )
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Aasan//Study plan//EN", "CALSCALE:GREGORIAN"]
    for b in blocks:
        bh, bm = map(int, b.start.split(":"))
        eh, em = divmod(bh * 60 + bm + b.minutes, 60)
        lines += [
            "BEGIN:VEVENT",
            f"UID:aasan-block-{b.id}@aasan",
            f"DTSTAMP:{stamp}",
            f"DTSTART;TZID=Asia/Kolkata:{b.date:%Y%m%d}T{bh:02d}{bm:02d}00",
            f"DTEND;TZID=Asia/Kolkata:{b.date:%Y%m%d}T{min(eh, 23):02d}{em if eh < 24 else 59:02d}00",
            f"SUMMARY:{_ics_text('Aasan: ' + (b.title or ('Today revision' if b.kind == 'today' else 'Study time')))}",
            "BEGIN:VALARM",
            "TRIGGER:-PT10M",
            "ACTION:DISPLAY",
            "DESCRIPTION:Study time with Aasan",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines += (
        []
        if blocks
        else [
            "BEGIN:VEVENT",
            f"UID:aasan-study-{user.id}@aasan",
            f"DTSTAMP:{stamp}",
            f"DTSTART;TZID=Asia/Kolkata:{start:%Y%m%d}T{int(hh):02d}{int(mm):02d}00",
            f"DTEND;TZID=Asia/Kolkata:{end_day:%Y%m%d}T{end_h % 24:02d}{end_m:02d}00",
            f"RRULE:FREQ=WEEKLY;BYDAY={byday}",
            "SUMMARY:Aasan study time",
            "DESCRIPTION:Your daily lesson + review on Aasan.",
            "BEGIN:VALARM",
            "TRIGGER:-PT10M",
            "ACTION:DISPLAY",
            "DESCRIPTION:Study time with Aasan",
            "END:VALARM",
            "END:VEVENT",
        ]
    )
    # Teacher-assigned courses with a due date (live feed keeps these up to date).
    # Same targeting as the learner's assignment list: their org as a whole (not partner-only members) or their classes.
    from apps.orgs.api import learner_assignments

    for a in learner_assignments(user).filter(
        due_at__isnull=False, due_at__gte=timezone.now() - timedelta(days=7)
    )[:50]:
        due = a.due_at.astimezone(UTC)
        title = _ics_text(f"Due: {(a.curriculum or a.scenario).title} ({a.org.name})")
        lines += [
            "BEGIN:VEVENT",
            f"UID:aasan-assignment-{a.id}-{user.id}@aasan",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{due:%Y%m%dT%H%M%SZ}",
            f"DTEND:{due:%Y%m%dT%H%M%SZ}",
            f"SUMMARY:{title}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _ics_text(s: str) -> str:
    """RFC 5545 escaping; also strips line breaks so user text can't inject calendar fields."""
    return (
        s.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r", " ")
        .replace("\n", " ")[:200]
    )


@api_view(["GET"])
def study_plan_ics(request):
    """Weekly study sessions as an .ics file (Google/Apple/Outlook calendar import)."""
    resp = HttpResponse(_ics(request.user), content_type="text/calendar; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="aasan-study-plan.ics"'
    return resp


@api_view(["GET"])
def week_plan(request):
    """This week: which planned study days are done (any XP) vs missed vs upcoming."""
    from apps.study.planner import paused_on

    prefs = upgrade(request.user.preferences.data)["learning"]
    start = week_start()
    xp_by_day = dict(
        XPEvent.objects.filter(user=request.user, day__gte=start).values_list("day").annotate(t=Sum("xp"))
    )
    today = timezone.localdate()
    # Days before the learner's first-ever activity can't be "missed".
    first_day = (
        XPEvent.objects.filter(user=request.user).order_by("day").values_list("day", flat=True).first()
        or today
    )
    days = []
    for i in range(7):
        d = start + timedelta(days=i)
        planned = d.weekday() in prefs["study_days"]
        xp = xp_by_day.get(d, 0)
        state = (
            "done"
            if xp > 0
            else ("upcoming" if d >= today else ("missed" if planned and d >= first_day else "rest"))
        )
        if xp == 0 and paused_on(request.user.id, d):
            state = "paused"
        days.append({"day": d, "weekday": d.weekday(), "planned": planned, "xp": xp, "state": state})
    return Response(
        {
            "days": days,
            "goal_minutes": prefs["daily_goal_minutes"],
            "time": (prefs["reminder_times"] or ["19:00"])[0],
        }
    )


@api_view(["GET"])
def nudges_view(request):
    return Response(nudges(request.user))


FEED_SALT = "aasan-calendar-feed"


def _feed_url(request, user) -> str:
    import secrets

    from django.core import signing

    p = user.profile
    if not p.calendar_nonce:
        p.calendar_nonce = secrets.token_hex(8)
        p.save(update_fields=["calendar_nonce"])
    token = signing.dumps({"u": user.id, "n": p.calendar_nonce}, salt=FEED_SALT, compress=True)
    return f"{settings.FRONTEND_URL}/api/game/calendar/{token}.ics"


@api_view(["GET", "POST"])
def calendar_feed(request):
    """GET: the learner's private subscription link. POST: rotate it (old link stops working)."""
    if request.method == "POST":
        import secrets

        request.user.profile.calendar_nonce = secrets.token_hex(8)
        request.user.profile.save(update_fields=["calendar_nonce"])
    return Response({"url": _feed_url(request, request.user)})


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
@authentication_classes([])
def calendar_feed_ics(request, token):
    """Subscribed calendars (Google/Apple/Outlook) poll this; it always reflects current plan + due dates."""
    from django.contrib.auth import get_user_model
    from django.core import signing

    try:
        data = signing.loads(token, salt=FEED_SALT)
    except signing.BadSignature:
        return HttpResponse(status=404)
    user = get_user_model().objects.filter(pk=data.get("u"), is_active=True).select_related("profile").first()
    if not user or not user.profile.calendar_nonce or user.profile.calendar_nonce != data.get("n"):
        return HttpResponse(status=404)
    resp = HttpResponse(_ics(user), content_type="text/calendar; charset=utf-8")
    resp["Cache-Control"] = "private, max-age=900"
    return resp
