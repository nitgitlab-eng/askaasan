from django.conf import settings
from django.db import models


def owner_deleted(collector, field, sub_objs, using):
    """Account deleted: personal notes go with it; an org knowledge-base document passes to another owner/admin of that org."""
    from apps.orgs.models import OrgDocument
    from apps.orgs.signals import kb_heir

    kb = {
        od.document_id: od.org_id
        for od in OrgDocument.objects.filter(document__in=list(sub_objs), source="kb")
    }
    rest = []
    for d in sub_objs:
        heir = kb_heir(kb[d.id], d.owner_id) if d.id in kb else None
        if heir:
            collector.add_field_update(field, heir, [d])
        else:
            rest.append(d)
    if rest:
        models.CASCADE(collector, field, rest, using)


class Document(models.Model):
    """A learner's uploaded notes. We keep only extracted text, never the raw file."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=owner_deleted, related_name="documents")
    title = models.CharField(max_length=200)
    filename = models.CharField(max_length=200)
    kind = models.CharField(max_length=8)  # pdf | docx | txt | md
    pages = models.PositiveIntegerField(default=0)
    chars = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Chunk(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    index = models.PositiveIntegerField()
    page = models.PositiveIntegerField(default=0)  # 1-based for PDFs; 0 = n/a
    text = models.TextField()
    embedding = models.JSONField(null=True, blank=True)  # set only when an embedding provider is configured

    class Meta:
        ordering = ["index"]
