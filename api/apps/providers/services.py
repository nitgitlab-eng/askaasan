"""Resolve the active provider config for a capability: admin DB row first,
then .env fallback. Also enforces per-user daily voice budgets."""

import os
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .catalog import CAPABILITIES, DEFAULT_LIMITS, ENV_KEYS
from .models import ProviderConfig, UsageCounter


@dataclass
class Resolved:
    capability: str
    provider: str
    model: str
    key: str
    voices: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)
    enabled: bool = True
    source: str = "default"  # db | env | default


def _env_route(capability: str) -> tuple[str, str] | None:
    # Back-compat with LLM_ROUTE_<TASK> / settings.LLM_ROUTES.
    task = {"tutor": "tutor", "utility": "grade"}.get(capability)
    if task and task in settings.LLM_ROUTES:
        provider, _, model = settings.LLM_ROUTES[task].partition(":")
        return provider, model
    return None


def resolve(capability: str) -> Resolved:
    spec = CAPABILITIES[capability]
    row = ProviderConfig.objects.filter(capability=capability).first()
    if row:
        provider, model, source = row.provider, row.model, "db"
    elif route := _env_route(capability):
        provider, model, source = *route, "env"
    else:
        provider, source = spec["default"], "default"
        model = spec["providers"][provider]["default_model"]

    key = (row.get_key() if row else "") or os.getenv(ENV_KEYS.get(provider, ""), "")
    return Resolved(
        capability=capability,
        provider=provider,
        model=model or spec["providers"].get(provider, {}).get("default_model", ""),
        key=key,
        voices=(row.voices if row else {}) or {},
        limits={**DEFAULT_LIMITS, **((row.limits if row else {}) or {})},
        enabled=row.enabled if row else True,
        source=source,
    )


def needs_key(provider: str, capability: str) -> bool:
    return not CAPABILITIES[capability]["providers"].get(provider, {}).get("no_key", False)


class BudgetExceeded(Exception):
    pass


# One AI budget unit covers a call of up to this many output tokens; bigger calls (course outlines, whole tests) cost
# proportionally more, so a daily unit limit bounds real spend rather than the number of requests.
AI_UNIT_TOKENS = 2000


def ai_units(max_tokens: int | None) -> int:
    """Budget units for one LLM call with this max_tokens (1 when unknown)."""
    if not max_tokens or max_tokens <= 0:
        return 1
    return max(1, -(-int(max_tokens) // AI_UNIT_TOKENS))


def charge(user, metric: str, amount: float, limit: float, *, max_tokens: int | None = None):
    """Atomically add usage; raise BudgetExceeded if it would pass the daily limit.
    With max_tokens, `amount` is per call and is multiplied by ai_units(max_tokens) (refund with the same arguments)."""
    if max_tokens is not None:
        amount = amount * ai_units(max_tokens)
    with transaction.atomic():
        row, _ = UsageCounter.objects.select_for_update().get_or_create(
            user=user, day=timezone.localdate(), metric=metric
        )
        if limit and row.amount + amount > limit:
            raise BudgetExceeded(metric)
        UsageCounter.objects.filter(pk=row.pk).update(amount=F("amount") + amount)
