"""/api/metrics/ (config/metrics.py): off without METRICS_TOKEN, 401 without it, Prometheus text with it."""

import pytest
from rest_framework.test import APIClient

from config.metrics import count


@pytest.mark.django_db
def test_metrics_need_the_token(settings):
    settings.METRICS_TOKEN = ""
    assert APIClient().get("/api/metrics/").status_code == 404
    settings.METRICS_TOKEN = "t" * 32
    assert APIClient().get("/api/metrics/").status_code == 401
    assert APIClient().get("/api/metrics/", HTTP_AUTHORIZATION="Bearer wrong").status_code == 401
    count("llm_errors", provider="anthropic", code="rate_limited")
    count("llm_errors", provider="anthropic", code="rate_limited")
    r = APIClient().get("/api/metrics/", HTTP_AUTHORIZATION="Bearer " + "t" * 32)
    body = r.content.decode()
    assert r.status_code == 200 and "aasan_up 1" in body and "aasan_disk_free_bytes" in body
    assert 'aasan_llm_errors_total{code="rate_limited",provider="anthropic"} 2' in body
    assert "aasan_webhook_failures_last_hour 0" in body
