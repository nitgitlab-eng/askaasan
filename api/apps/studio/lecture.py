"""Lecture video pipeline: (upload →) speech-to-text → AI segments with checkpoint questions."""

import logging
import re

from django.conf import settings

from .models import LectureVideo

log = logging.getLogger(__name__)
TS = re.compile(r"^\s*\[?(?:(\d+):)?(\d{1,2}):(\d{2})\]?\s*(.*)$")


def _timestamped(transcript: str, duration: int) -> str:
    """Normalise to '[seconds] text' lines. YouTube's copied transcript (timestamp line, then text) and
    '[mm:ss] text' both work; plain text gets times spread evenly over the duration."""
    lines = [ln for ln in transcript.splitlines() if ln.strip()]
    out, pending = [], None
    for ln in lines:
        m = TS.match(ln)
        if m:
            h, mnt, sec, rest = m.groups()
            t = int(h or 0) * 3600 + int(mnt) * 60 + int(sec)
            if rest.strip():
                out.append(f"[{t}] {rest.strip()}")
                pending = None
            else:
                pending = t
        elif pending is not None:
            out.append(f"[{pending}] {ln.strip()}")
            pending = None
        else:
            out.append(ln.strip())
    if out and all(not o.startswith("[") for o in out):  # no timestamps at all
        total = max(1, sum(len(o) for o in out))
        acc, timed = 0, []
        for o in out:
            timed.append(f"[{int(duration * acc / total)}] {o}")
            acc += len(o)
        out = timed
    return "\n".join(out)[:60000]


MAX_STT_SECONDS = 4 * 3600  # same ceiling as a lecture's duration


def _transcribe(lv: LectureVideo) -> str:
    from apps.providers.services import BudgetExceeded, charge
    from apps.providers.services import resolve as resolve_cfg
    from apps.providers.voice.adapters import transcribe

    cfg = resolve_cfg("stt")
    if cfg.provider == "browser" or not cfg.enabled:
        raise RuntimeError("stt_not_configured")
    with lv.file.open("rb") as fh:
        audio = fh.read()
    # The whole file goes to the provider: charge the creator's STT budget first (the larger of the reported
    # duration and a size estimate: ~128 kbps audio, ~1 Mbps video), and give it back if nothing was transcribed.
    per_second = 125_000 if (lv.mime or "").startswith("video/") else 16_000
    seconds = min(MAX_STT_SECONDS, max(float(lv.duration or 0), len(audio) / per_second, 1.0))
    try:
        charge(lv.owner, "stt_seconds", seconds, cfg.limits.get("stt_seconds_per_day", 0))
    except BudgetExceeded as e:
        raise RuntimeError("stt_budget_exceeded") from e
    lang = lv.subsection.section.curriculum.language
    try:
        return transcribe(cfg, audio, lv.mime, lang if lang in ("en", "ta") else None)
    except Exception:
        charge(lv.owner, "stt_seconds", -seconds, 0)
        raise


def process(lecture_id: int) -> None:
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.studio import SEGMENT_SYSTEM, SegmentPlan
    from llm.structured import complete_json_sync

    lv = LectureVideo.objects.select_related("subsection__section__curriculum").get(pk=lecture_id)
    try:
        if lv.kind == "upload" and not lv.transcript:
            lv.transcript = _transcribe(lv)
            lv.status = LectureVideo.Status.SEGMENTING
            lv.save(update_fields=["transcript", "status"])
        duration = lv.duration or 3600
        text = _timestamped(lv.transcript, duration)
        lang = lv.subsection.section.curriculum.language
        plan = complete_json_sync(
            "author",
            SEGMENT_SYSTEM.format(duration=duration, lang_rule=LANG_RULE.get(lang, LANG_RULE["en"])),
            f"Lesson: {lv.subsection.title}\nTRANSCRIPT ([seconds] text):\n{text}",
            SegmentPlan,
            max_tokens=6000,
        )
        segs = []
        for s in plan.segments[:8]:
            start = max(0, min(s.start, duration))
            end = max(start + 1, min(s.end, duration))
            cps = [
                {
                    "at": max(start, min(c.at, end)),
                    "question": c.question,
                    "options": c.options[:6],
                    "correct": c.correct,
                }
                for c in s.checkpoints[:2]
                if len(c.options) >= 2 and c.correct and all(0 <= i < len(c.options) for i in c.correct)
            ]
            segs.append(
                {
                    "start": start,
                    "end": end,
                    "title": s.title[:200],
                    "summary": s.summary[:400],
                    "checkpoints": cps,
                }
            )
        lv.segments, lv.status, lv.error = segs, LectureVideo.Status.READY, ""
    except Exception as e:
        log.exception("lecture %s failed", lecture_id)
        lv.status, lv.error = LectureVideo.Status.FAILED, (getattr(e, "code", "") or str(e))[:300]
    lv.save()


def enqueue_process(lecture_id: int) -> None:
    if getattr(settings, "LEARNING_JOBS_INLINE", False):
        process(lecture_id)
    elif settings.REDIS_URL:
        from .tasks import process_lecture

        process_lecture.delay(lecture_id)
    else:
        from apps.learning.jobs import _thread

        _thread(process, lecture_id)
