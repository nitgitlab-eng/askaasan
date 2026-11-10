"""P5: the daily 'Today' screen — themed revision stations, swaps, a focus theme and a revision leaderboard."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import DailyRevision

KEYS = ("review", "weak", "quiz", "roleplay")
MAX_SWAPS = 10


def _matches_focus(texts, focus: str) -> bool:
    if not focus:
        return True
    from apps.paths.services import match_skills

    return focus in match_skills([t for t in texts if t])


def _viewable(user):
    """Course ids the learner can still open; Today never points at a course whose access has ended."""
    from apps.learning.access import viewable_curricula

    return viewable_curricula(user).values("id")


def _review_station(user, focus, alt):
    from apps.review.models import ReviewCard

    due = ReviewCard.objects.filter(
        user=user, due__lte=timezone.now(), activity__subsection__section__curriculum__in=_viewable(user)
    ).select_related("activity__subsection")
    if focus:
        due = [
            c
            for c in due[:300]
            if _matches_focus([*c.activity.subsection.skills, c.activity.subsection.title], focus)
        ]
        n = len(due)
    else:
        n = due.count()
    if not n:
        return None
    link = "/review" + (f"?focus={focus}" if focus else "")
    return {
        "key": "review",
        "kind": "review",
        "title": "",
        "n": min(n, 20),
        "link": link,
        "minutes": max(2, min(n, 20) // 2),
    }


def _weak_candidates(user, focus):
    from apps.review.models import MasteryRecord

    out = []
    for m in (
        MasteryRecord.objects.filter(
            user=user, p_known__lt=0.75, subsection__section__curriculum__in=_viewable(user)
        )
        .select_related("subsection__section__curriculum")
        .order_by("p_known")[:40]
    ):
        sub = m.subsection
        if _matches_focus([*sub.skills, sub.title, *(sub.section.curriculum.skills or [])], focus):
            out.append(
                {
                    "key": "weak",
                    "kind": "practice",
                    "title": sub.title,
                    "course": sub.section.curriculum.title,
                    "pct": int(m.p_known * 100),
                    "link": f"/learn/{sub.section.curriculum_id}/lesson/{sub.id}/practice",
                    "minutes": 5,
                }
            )
    return out


def _quiz_station(user, focus):
    from apps.review.models import ReviewCard

    if ReviewCard.objects.filter(user=user).count() < 3:
        return None
    link = "/review?mode=quick" + (f"&focus={focus}" if focus else "")
    return {"key": "quiz", "kind": "quiz", "title": "", "n": 5, "link": link, "minutes": 3}


def _roleplay_candidates(user, focus):
    from apps.roleplay.library import ensure_library
    from apps.roleplay.models import RolePlaySession, Scenario

    # A fresh deployment has no scenarios until someone opens role-play; Today must not stay empty until then.
    ensure_library()
    done = set(
        RolePlaySession.objects.filter(
            user=user, started_at__gte=timezone.now() - timedelta(days=14)
        ).values_list("scenario_id", flat=True)
    )
    qs = Scenario.objects.filter(source="library").exclude(id__in=done).order_by("id")
    out = [
        {
            "key": "roleplay",
            "kind": "roleplay",
            "title": s.title,
            "emoji": s.emoji,
            "link": f"/roleplay/{s.id}",
            "minutes": 5,
        }
        for s in qs[:30]
        if _matches_focus([s.title, s.summary], focus)
    ]
    return out or (
        [
            {
                "key": "roleplay",
                "kind": "roleplay",
                "title": s.title,
                "emoji": s.emoji,
                "link": f"/roleplay/{s.id}",
                "minutes": 5,
            }
            for s in qs[:30]
        ]
        if focus
        else []
    )


def _lesson_station(user):
    from apps.learning.models import UserSubsectionState

    st = (
        UserSubsectionState.objects.filter(
            user=user, status="in_progress", subsection__section__curriculum__in=_viewable(user)
        )
        .select_related("subsection__section__curriculum")
        .order_by("-started_at")
        .first()
    )
    if not st:
        return None
    sub = st.subsection
    return {
        "key": "lesson",
        "kind": "lesson",
        "title": sub.title,
        "course": sub.section.curriculum.title,
        "link": f"/learn/{sub.section.curriculum_id}/lesson/{sub.id}",
        "minutes": 10,
    }


TIERS = [
    ("seedling", 0),
    ("sprout", 10),
    ("explorer", 30),
    ("achiever", 75),
    ("scholar", 150),
    ("master", 300),
]


def _exam_station(user):
    from apps.review.models import ReviewCard

    if ReviewCard.objects.filter(user=user).count() < 10:
        return None
    return {"key": "exam", "kind": "exam", "title": "", "n": 10, "link": "/review?mode=exam", "minutes": 5}


def build(user, focus: str, alts: dict[str, int], day, circuits: int = 1) -> list[dict]:
    """All rounds for the day. Round 1 = the usual stations; each extra circuit = fresh alternatives + a timed exam."""
    out = []
    for n in range(1, circuits + 1):
        suffix = "" if n == 1 else f"@{n}"
        # Only weak/roleplay have alternatives; later rounds start further along so they offer something new.
        rnd = _round(user, focus, {k: alts.get(k + suffix, 0) + (n - 1) for k in ("weak", "roleplay")}, day)
        if n > 1:
            rnd = [s for s in rnd if s["key"] in ("weak", "quiz", "roleplay")]
            if ex := _exam_station(user):
                rnd.append(ex)
        out += [{**s, "key": s["key"] + suffix, "round": n} for s in rnd]
    return out


def _round(user, focus: str, alts: dict[str, int], day) -> list[dict]:
    seed = day.toordinal() + user.id  # stable "random" pick per learner per day
    stations = []
    if r := _review_station(user, focus, 0):
        stations.append(r)
    weak = _weak_candidates(user, focus)
    if weak:
        stations.append({**weak[alts.get("weak", 0) % len(weak)], "alts": len(weak)})
    if q := _quiz_station(user, focus):
        stations.append(q)
    rps = _roleplay_candidates(user, focus)
    if rps:
        stations.append({**rps[(seed + alts.get("roleplay", 0)) % len(rps)], "alts": len(rps)})
    if len(stations) < 3 and (ls := _lesson_station(user)):
        stations.append(ls)
    return stations


def _state(user, refresh=False, focus=None):
    day = timezone.localdate()
    with transaction.atomic():
        dr, created = DailyRevision.objects.select_for_update().get_or_create(user=user, day=day)
        if focus is not None:
            dr.focus, refresh = focus, True
        if created or refresh or not dr.stations:
            alts = {s["key"]: s.get("alt", 0) for s in dr.stations}
            dr.stations = [
                {**s, "alt": alts.get(s["key"], 0)} for s in build(user, dr.focus, alts, day, dr.circuits)
            ]
            dr.save()
    return dr


def _auto_done(user, dr):
    """Stations finish themselves when the underlying work is done (e.g. no reviews left)."""
    from apps.review.models import ReviewCard

    changed = False
    if (
        any(s["key"] == "review" for s in dr.stations)
        and "review" not in dr.done
        and not ReviewCard.objects.filter(
            user=user, due__lte=timezone.now(), activity__subsection__section__curriculum__in=_viewable(user)
        ).exists()
    ):
        dr.done = [*dr.done, "review"]
        changed = True
    if changed:
        dr.save(update_fields=["done"])


def _out(user, dr):
    from apps.paths.models import UserSkill

    _auto_done(user, dr)
    followed = [
        {"slug": us.skill.slug, "name": us.skill.name, "name_ta": us.skill.name_ta}
        for us in UserSkill.objects.filter(user=user, followed=True, hidden=False)
        .select_related("skill")
        .order_by("order")[:12]
    ]
    total = sum(1 for s in dr.stations)
    done = len([k for k in dr.done if any(s["key"] == k for s in dr.stations)])
    return {
        "day": dr.day,
        "focus": dr.focus,
        "stations": [{**s, "done": s["key"] in dr.done} for s in dr.stations],
        "done": done,
        "total": total,
        "circuits": dr.circuits,
        "can_add_circuit": bool(total) and done >= total and dr.circuits < MAX_CIRCUITS,
        "swaps_left": max(0, MAX_SWAPS - dr.swaps),
        "themes": followed,
        "tier": tier_of(user),
    }


MAX_CIRCUITS = 5


def tier_of(user) -> dict:
    """Programme map: revision points (stations finished, all time) → level tier."""
    points = sum(len(d) for d in DailyRevision.objects.filter(user=user).values_list("done", flat=True))
    idx = max(i for i, (_, need) in enumerate(TIERS) if points >= need)
    nxt = TIERS[idx + 1] if idx + 1 < len(TIERS) else None
    return {
        "points": points,
        "level": idx + 1,
        "key": TIERS[idx][0],
        "next": nxt[0] if nxt else None,
        "next_at": nxt[1] if nxt else None,
        "tiers": [{"key": k, "at": n} for k, n in TIERS],
    }


@api_view(["POST"])
def today_circuit(request):
    """'One more circuit': once every station is done, add a fresh round (with a timed exam)."""
    dr = _state(request.user)
    out = _out(request.user, dr)
    if not out["can_add_circuit"]:
        return Response(
            {"code": "finish_first" if dr.circuits < MAX_CIRCUITS else "enough_for_today"},
            status=status.HTTP_409_CONFLICT,
        )
    dr.circuits += 1
    dr.save(update_fields=["circuits"])
    return Response(_out(request.user, _state(request.user, refresh=True)))


@api_view(["GET"])
def today(request):
    return Response(
        _out(request.user, _state(request.user, refresh=request.query_params.get("refresh") == "1"))
    )


@api_view(["POST"])
def today_focus(request):
    focus = str(request.data.get("focus") or "")[:60]
    if focus:
        from apps.paths.models import Skill

        if not Skill.objects.filter(slug=focus).exists():
            return Response({"code": "unknown_skill"}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_out(request.user, _state(request.user, focus=focus)))


@api_view(["POST"])
def today_swap(request):
    """'Another one': move a station to its next alternative."""
    key = request.data.get("key")
    dr = _state(request.user)
    if (
        not isinstance(key, str)
        or key.split("@")[0] not in ("weak", "roleplay")
        or not any(s["key"] == key for s in dr.stations)
    ):
        return Response({"code": "not_swappable"}, status=status.HTTP_400_BAD_REQUEST)
    if dr.swaps >= MAX_SWAPS:
        return Response({"code": "no_swaps_left"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    alts = {s["key"]: s.get("alt", 0) for s in dr.stations}
    alts[key] = alts.get(key, 0) + 1
    dr.stations = [
        {**s, "alt": alts.get(s["key"], 0)} for s in build(request.user, dr.focus, alts, dr.day, dr.circuits)
    ]
    dr.swaps += 1
    dr.done = [k for k in dr.done if k != key]
    dr.save()
    return Response(_out(request.user, dr))


@api_view(["POST"])
def today_done(request):
    key = request.data.get("key")
    dr = _state(request.user)
    if not any(s["key"] == key for s in dr.stations):
        return Response({"code": "unknown_station"}, status=status.HTTP_400_BAD_REQUEST)
    reward = None
    if key not in dr.done:
        dr.done = [*dr.done, key]
        dr.save(update_fields=["done"])
        if all(s["key"] in dr.done for s in dr.stations):
            from apps.game.services import award

            ref = f"today:{dr.day}" if dr.circuits == 1 else f"today:{dr.day}:{dr.circuits}"
            reward = award(
                request.user,
                "today_complete",
                ref=ref,
                xp=20 if dr.circuits == 1 else 10,
                coins=5 if dr.circuits == 1 else 2,
            )
    return Response({**_out(request.user, dr), "reward": reward})


@api_view(["GET"])
def revision_board(request):
    """This week's revision leaderboard (reviews + Today stations). Hidden learners still see their own row."""
    from django.db.models import Count

    from apps.game.models import PlayerStats
    from apps.game.services import stats_for, week_start
    from apps.orgs.extras import blocked, feature_off_response, hidden_from_boards
    from apps.review.models import ReviewLog

    if blocked(request.user, "leaderboard"):
        return feature_off_response("leaderboard")
    start = week_start()
    reviews = dict(
        ReviewLog.objects.filter(created_at__date__gte=start)
        .values_list("card__user_id")
        .annotate(n=Count("id"))
    )
    stations: dict[int, int] = {}
    for uid, done in DailyRevision.objects.filter(day__gte=start).values_list("user_id", "done"):
        stations[uid] = stations.get(uid, 0) + len(done)
    scores = {u: reviews.get(u, 0) + 3 * stations.get(u, 0) for u in set(reviews) | set(stations)}
    visible = set(
        PlayerStats.objects.filter(user_id__in=scores, show_on_leaderboard=True)
        .exclude(user_id__in=hidden_from_boards())
        .values_list("user_id", flat=True)
    )
    from apps.accounts.models import User

    names = {
        u.id: (u.profile.display_name or u.email.split("@")[0])[:24]
        for u in User.objects.filter(id__in=scores).select_related("profile")
    }
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    rows = []
    for i, (uid, sc) in enumerate(ranked, 1):
        if uid in visible or uid == request.user.id:
            rows.append(
                {
                    "rank": i,
                    "name": names.get(uid, "—"),
                    "score": sc,
                    "reviews": reviews.get(uid, 0),
                    "stations": stations.get(uid, 0),
                    "me": uid == request.user.id,
                }
            )
    me = next((r for r in rows if r["me"]), None)
    return Response(
        {
            "rows": [r for r in rows if r["rank"] <= 20 or r["me"]][:21],
            "me": me,
            "visible": stats_for(request.user).show_on_leaderboard,
        }
    )
