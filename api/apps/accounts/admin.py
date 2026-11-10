from django.contrib import admin
from django.contrib.auth import forms as auth_forms
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import PasskeyCredential, Profile, User, UserPreferences


class UserChangeForm(auth_forms.UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


class UserCreationForm(auth_forms.BaseUserCreationForm):
    class Meta:
        model = User
        fields = ("email",)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Email-based users; the password is shown only as a hash summary (never an editable field), and only a
    superuser can grant superuser, staff, group or permission rights."""

    form = UserChangeForm
    add_form = UserCreationForm
    ordering = ("email",)
    list_display = ("email", "is_staff", "is_active", "date_joined")
    search_fields = ("email",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Status", {"fields": ("is_active", "email_verified", "is_creator", "age_band", "guardian_email")}),
        ("Permissions", {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)

    def get_readonly_fields(self, request, obj=None):
        ro = tuple(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            ro += ("is_staff", "is_superuser", "groups", "user_permissions")
        return ro

    def has_change_permission(self, request, obj=None):
        # Staff can't edit (or reset the password of) a superuser: that would be a way to become one.
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj)


admin.site.register(Profile)
admin.site.register(UserPreferences)
admin.site.register(PasskeyCredential)
