from urllib.parse import urlsplit

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import (
    AuditLog,
    BlockedDomain,
    Link,
)


@admin.action(description="Disable selected links as abusive")
def block_links(modeladmin, request, queryset):
    moderate(request, queryset, Link.Status.BLOCKED)


@admin.action(description="Restore selected links to active")
def restore_links(modeladmin, request, queryset):
    moderate(request, queryset, Link.Status.ACTIVE)


def moderate(request, queryset, status):
    with transaction.atomic():
        for link in queryset.select_for_update():
            link.status = status
            link.rules_version += 1
            link.save(update_fields=["status", "rules_version", "updated_at"])
            AuditLog.objects.create(actor=request.user, link=link, action=f"admin.{status}")


class DomainForm(forms.ModelForm):
    class Meta:
        model = BlockedDomain
        fields = "__all__"

    def clean_hostname(self):
        value = self.cleaned_data["hostname"].strip().rstrip(".").lower()
        try:
            value = value.encode("idna").decode("ascii")
            host = urlsplit("https://" + value).hostname
        except (ValueError, UnicodeError):
            raise ValidationError("Enter a hostname such as example.com.") from None
        if host != value or "." not in value or any(c in value for c in "/:@?# "):
            raise ValidationError("Enter only a hostname, without a scheme, port, or path.")
        return value


@admin.register(BlockedDomain)
class BlockedDomainAdmin(admin.ModelAdmin):
    form = DomainForm
    list_display = ["hostname", "reason", "enabled"]
    search_fields = ["hostname"]
