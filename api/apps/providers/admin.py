from django.contrib import admin

from .models import ProviderConfig, UsageCounter


@admin.register(ProviderConfig)
class ProviderConfigAdmin(admin.ModelAdmin):
    list_display = ("capability", "provider", "model", "enabled", "updated_at")
    exclude = ("encrypted_key",)  # manage keys in the Aasan admin console


admin.site.register(UsageCounter)
