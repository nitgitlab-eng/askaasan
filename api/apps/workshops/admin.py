from django.contrib import admin

from .models import Workshop, WorkshopRun


@admin.register(Workshop)
class WorkshopAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "duration_minutes", "proctoring", "is_published")


@admin.register(WorkshopRun)
class WorkshopRunAdmin(admin.ModelAdmin):
    list_display = ("workshop", "audience", "starts_at", "status", "price_paise")
