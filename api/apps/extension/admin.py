from django.contrib import admin

from .models import ExtensionToken


@admin.register(ExtensionToken)
class ExtensionTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "created_at", "last_used_at", "revoked_at")
    readonly_fields = ("token_hash",)
