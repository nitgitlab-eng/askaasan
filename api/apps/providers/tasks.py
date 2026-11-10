"""AI spend alerts: staff (DJANGO_ADMINS) hear when this month's AI cost crosses 50%, 80% and 95% of LLM_MONTHLY_BUDGET
(rupees, priced from the admin console's model prices). Each threshold mails once a month."""

import logging
from decimal import Decimal

from celery import shared_task
from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

log = logging.getLogger(__name__)
THRESHOLDS = (50, 80, 95)


def month_cost() -> Decimal:
    from .models import LLMUsage
    from .overview import _cost, _price_map

    start = timezone.localdate().replace(day=1)
    prices = _price_map()
    total = Decimal(0)
    for r in (
        LLMUsage.objects.filter(created_at__date__gte=start)
        .values("provider", "model")
        .annotate(tin=Sum("input_tokens"), tout=Sum("output_tokens"))
    ):
        total += _cost(prices, r["provider"], r["model"], r["tin"] or 0, r["tout"] or 0) or 0
    return total


@shared_task
def spend_check() -> dict:
    from django.core.mail import mail_admins

    from apps.accounts import counters

    budget = settings.LLM_MONTHLY_BUDGET
    if budget <= 0:
        return {"budget": 0}
    cost = month_cost()
    pct = float(cost / Decimal(budget) * 100)
    month = timezone.localdate().strftime("%Y-%m")
    crossed = [t for t in THRESHOLDS if pct >= t]
    if crossed and counters.store().add(f"llm-spend:{month}:{crossed[-1]}", 1, 40 * 24 * 3600):
        log.warning("AI spend at %.0f%% of the monthly budget (₹%.0f of ₹%s)", pct, cost, budget)
        mail_admins(
            f"AI spend at {crossed[-1]}% of this month's budget",
            f"This month's AI cost is about ₹{cost:,.0f} of the ₹{budget:,} budget ({pct:.0f}%).\n"
            "See Admin → Overview → AI for the models and tasks behind it. Raise LLM_MONTHLY_BUDGET, lower plan "
            "limits, or route utility tasks to a cheaper model.",
            fail_silently=True,
        )
    return {"cost": float(cost), "pct": round(pct, 1)}
