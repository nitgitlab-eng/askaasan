"""Data retention (privacy page, "How long we keep your data"). Each window is a setting; 0 keeps forever.

Workshop transcripts have their own job (apps.workshops.tasks.clean_old_activity). Documents and the account itself
stay until the learner deletes them."""

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone


def _cutoff(days: int):
    return timezone.now() - timedelta(days=days) if days > 0 else None


@shared_task
def apply_retention() -> dict:
    from django.core.files.storage import default_storage

    from apps.mentor.models import Conversation
    from apps.providers.models import LLMUsage, SpeechClip
    from apps.roleplay.models import RolePlayTurn

    out = {}
    if cut := _cutoff(settings.MENTOR_RETENTION_DAYS):  # untouched conversations go with their messages
        out["conversations"] = Conversation.objects.filter(updated_at__lt=cut).delete()[0]
    if cut := _cutoff(settings.ROLEPLAY_RETENTION_DAYS):  # transcripts go; sessions and scores stay
        out["roleplay_turns"] = RolePlayTurn.objects.filter(created_at__lt=cut).delete()[0]
    if cut := _cutoff(settings.LLM_USAGE_RETENTION_DAYS):  # token counts only, no content
        out["llm_usage"] = LLMUsage.objects.filter(created_at__lt=cut).delete()[0]
    if cut := _cutoff(
        settings.SPEECH_CLIP_RETENTION_DAYS
    ):  # made again (and charged) if a line is needed later
        n = 0
        for clip in SpeechClip.objects.filter(created_at__lt=cut).iterator():
            default_storage.delete(clip.file)
            clip.delete()
            n += 1
        out["speech_clips"] = n
    return out
