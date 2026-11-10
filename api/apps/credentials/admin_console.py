"""Admin console: certificates and certificate templates; plus an organisation's own templates (org admins).

Staff (/api/admin/):
  GET   certificates/                     ?q= &kind= &org= &status=active|revoked &page= &export=csv  (+ stats)
  POST  certificates/<id>/revoke/         permanent
  POST  certificates/<id>/refresh-name/   re-read the learner's display name (e.g. after a spelling fix)
  GET   certificate-templates/            platform templates
  POST  certificate-templates/            create or update one scope {kind, language, ...fields}
  PATCH/DELETE certificate-templates/<id>/
  POST  certificate-templates/preview/    {kind?, ...fields} → sample PDF
Org admins (/api/credentials/orgs/<slug>/):
  GET/POST templates/, PATCH/DELETE templates/<id>/, POST templates/preview/
"""

from datetime import timedelta

from django.db import IntegrityError
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.admin_paging import paged
from apps.accounts.staff import AdminSection

from . import templates as tpl
from .models import Certificate, CertificateTemplate
from .services import learner_name, org_issuer_name

admin_view = permission_classes([AdminSection])


def _cert_row(c: Certificate) -> dict:
    return {
        "id": c.id,
        "code": c.code,
        "kind": c.kind,
        "title": c.title,
        "learner": c.learner_name,
        "email": c.user.email,
        "issuer": c.issuer_name,
        "org_id": c.org_id,
        "issued_at": c.issued_at,
        "revoked": bool(c.revoked_at),
        "hidden": c.hidden,
    }


@api_view(["GET"])
@admin_view
def certificates(request):
    qs = Certificate.objects.select_related("user").order_by("-issued_at")
    if q := str(request.query_params.get("q") or "").strip()[:80]:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(learner_name__icontains=q)
            | Q(code__icontains=q)
            | Q(user__email__icontains=q)
            | Q(issuer_name__icontains=q)
        )
    if (kind := request.query_params.get("kind")) in tpl.KINDS:
        qs = qs.filter(kind=kind)
    if (org := request.query_params.get("org")) and org.isdigit():
        qs = qs.filter(org_id=int(org))
    st = request.query_params.get("status")
    if st == "active":
        qs = qs.filter(revoked_at=None)
    elif st == "revoked":
        qs = qs.exclude(revoked_at=None)
    since = timezone.now() - timedelta(days=30)
    stats = {
        "total": Certificate.objects.count(),
        "last_30d": Certificate.objects.filter(issued_at__gte=since).count(),
        "revoked": Certificate.objects.exclude(revoked_at=None).count(),
        "by_kind": dict(Certificate.objects.values_list("kind").annotate(n=Count("id"))),
    }
    return paged(request, qs, _cert_row, name="certificates", extra={"stats": stats})


@api_view(["POST"])
@admin_view
def certificate_revoke(request, pk):
    c = get_object_or_404(Certificate, pk=pk)
    if not c.revoked_at:
        c.revoked_at = timezone.now()
        c.save(update_fields=["revoked_at"])
    return Response(_cert_row(c))


@api_view(["POST"])
@admin_view
def certificate_refresh_name(request, pk):
    c = get_object_or_404(Certificate.objects.select_related("user"), pk=pk)
    if c.revoked_at:
        return Response({"code": "revoked"}, status=status.HTTP_409_CONFLICT)
    c.learner_name = learner_name(c.user)
    c.save(update_fields=["learner_name"])
    return Response(_cert_row(c))


# ── templates (shared by staff and org admins) ───────────────────────


def _list(org):
    qs = (
        CertificateTemplate.objects.filter(org=org)
        if org
        else CertificateTemplate.objects.filter(org__isnull=True)
    )
    return Response([tpl.template_out(t) for t in qs.order_by("kind", "language")])


def _save(request, org, t: CertificateTemplate | None = None):
    data = request.data if isinstance(request.data, dict) else {}
    fields, err = tpl.clean(data)
    if err:
        return Response({"code": err}, status=status.HTTP_400_BAD_REQUEST)
    if t is None:  # POST: create or update the template for this scope
        scope = {"org": org, "kind": fields.pop("kind", ""), "language": fields.pop("language", "")}
        t = CertificateTemplate.objects.filter(**scope).first() or CertificateTemplate(**scope)
        created = t.pk is None
    else:
        created = False
    for k, v in fields.items():
        setattr(t, k, v)
    t.updated_by = request.user
    try:
        t.save()
    except IntegrityError:
        return Response({"code": "scope_taken"}, status=status.HTTP_409_CONFLICT)
    return Response(tpl.template_out(t), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


def _one(request, org, pk):
    t = (
        get_object_or_404(CertificateTemplate, pk=pk, org=org)
        if org
        else get_object_or_404(CertificateTemplate, pk=pk, org__isnull=True)
    )
    if request.method == "DELETE":
        t.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    return _save(request, org, t)


def _preview(request, org):
    from .pdf import render

    data = request.data if isinstance(request.data, dict) else {}
    fields, err = tpl.clean(data)
    if err:
        return Response({"code": err}, status=status.HTTP_400_BAD_REQUEST)
    kind = fields.pop("kind", "") or "course"
    fields.pop("language", None)
    fields.pop("active", None)
    look = tpl.look_of(CertificateTemplate(**fields))
    issuer = "Aasan"
    if org:
        try:
            issuer = org_issuer_name(org)
        except Exception:  # noqa: BLE001 — a reserved display name still previews, with the plain name
            issuer = org.name
    pdf = render(tpl.sample(kind, issuer, org), look)
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = 'inline; filename="certificate-preview.pdf"'
    return resp


@api_view(["GET", "POST"])
@admin_view
def templates(request):
    return _list(None) if request.method == "GET" else _save(request, None)


@api_view(["PATCH", "DELETE"])
@admin_view
def template_detail(request, pk):
    return _one(request, None, pk)


@api_view(["POST"])
@admin_view
def template_preview(request):
    return _preview(request, None)


# Organisation admins: their own templates (owner/admin only; managers can issue but not restyle)


def _org(request, slug):
    from apps.orgs.perms import require

    return require(request.user, slug, "admin").org


@api_view(["GET", "POST"])
def org_templates(request, slug):
    org = _org(request, slug)
    return _list(org) if request.method == "GET" else _save(request, org)


@api_view(["PATCH", "DELETE"])
def org_template_detail(request, slug, pk):
    return _one(request, _org(request, slug), pk)


@api_view(["POST"])
def org_template_preview(request, slug):
    return _preview(request, _org(request, slug))
