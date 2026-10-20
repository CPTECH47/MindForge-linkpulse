from django.contrib import admin

from ..models import (
    AuditLog,
    ClickEvent,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ClickEvent)
class ClickAdmin(ReadOnlyAdmin):
    list_display = ["id", "link", "outcome", "occurred_at", "is_bot", "processed_at", "retry_count"]
    list_filter = ["outcome", "is_bot"]


@admin.register(AuditLog)
class AuditAdmin(ReadOnlyAdmin):
    list_display = ["created_at", "actor", "link", "action"]
