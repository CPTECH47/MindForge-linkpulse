from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.shortcuts import redirect

from ..forms import AdminLinkForm
from ..models import (
    Campaign,
    Folder,
    Link,
    PlatformSettings,
    Tag,
    Workspace,
)
from ..services.links import save_link
from .moderation import block_links, restore_links


@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    form = AdminLinkForm
    list_display = ["alias", "title", "workspace", "status", "successful_redirects", "created_at"]
    list_filter = ["status", "workspace"]
    search_fields = ["alias", "title", "destination"]
    readonly_fields = ["successful_redirects", "rules_version", "created_at", "updated_at"]
    exclude = ["password_hash"]
    actions = [block_links, restore_links]

    def save_model(self, request, obj, form, change):
        instance = Link.objects.get(pk=obj.pk) if change else None
        saved = save_link(
            request.user, form.cleaned_data["workspace"], form.cleaned_data, instance, administrator=True
        )
        obj.__dict__.update(saved.__dict__)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except ValidationError as error:
            self.message_user(request, "; ".join(error.messages), level=messages.ERROR)
            return redirect(request.path)

    def has_delete_permission(self, request, obj=None):
        return False


class GroupAdmin(admin.ModelAdmin):
    list_display = ["name", "workspace", "archived"]
    list_filter = ["workspace", "archived"]
    search_fields = ["name"]
    actions = None

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or not obj.links.exists())

    def get_readonly_fields(self, request, obj=None):
        return ["workspace"] if obj else []


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "created_at"]
    search_fields = ["name", "owner__username"]
    readonly_fields = ["created_at"]

    def has_delete_permission(self, request, obj=None):
        return False


class PolicyForm(forms.ModelForm):
    class Meta:
        model = PlatformSettings
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, maximum in [
            ("creation_rate_limit", 10000),
            ("password_rate_limit", 100),
            ("event_retention_days", 3650),
        ]:
            self.fields[name].validators.extend([MinValueValidator(1), MaxValueValidator(maximum)])


@admin.register(PlatformSettings)
class PolicyAdmin(admin.ModelAdmin):
    form = PolicyForm

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not PlatformSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


for model in [Campaign, Folder, Tag]:
    admin.site.register(model, GroupAdmin)
