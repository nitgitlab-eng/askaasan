"""Paging and CSV export for admin console lists: ?page=N (50 per page) and ?export=csv (up to 5,000 rows)."""

import csv
import io
from collections.abc import Callable

from django.http import HttpResponse
from rest_framework.response import Response

PAGE_SIZE = 50
CSV_MAX = 5000


def _flat(row: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in row.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flat(v, f"{key}."))
        elif isinstance(v, list):
            out[key] = "; ".join(str(x) for x in v)
        else:
            out[key] = "" if v is None else v
    return out


def _safe(v):
    """Spreadsheet formula injection: a cell starting with = + - @ is shown as text."""
    s = str(v)
    return f"'{s}" if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def paged(request, qs, row: Callable[[object], dict], *, name: str = "export", extra: dict | None = None):
    if request.query_params.get("export") == "csv":
        rows = [_flat(row(o)) for o in qs[:CSV_MAX]]
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0]), extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: _safe(v) for k, v in r.items()})
        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="aasan-{name}.csv"'
        return resp
    try:
        page = max(1, int(request.query_params.get("page") or 1))
    except ValueError:
        page = 1
    count = qs.count()
    items = [row(o) for o in qs[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]]
    return Response(
        {
            "results": items,
            "count": count,
            "page": page,
            "pages": max(1, -(-count // PAGE_SIZE)),
            **(extra or {}),
        }
    )
