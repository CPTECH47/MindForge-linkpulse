from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from ..context_processors import current_workspace
from ..models import AuditLog, Campaign, ClickEvent, Tag
from ..services.analytics import analytics
from ..services.tracking import geolocation_status


def report_filters(request):
    try:
        days = int(request.GET.get("days", "7"))
        campaign = int(request.GET["campaign"]) if request.GET.get("campaign") else None
        link_id = int(request.GET["link"]) if request.GET.get("link") else None
    except ValueError:
        return 7, None, None
    return days if days in {7, 30, 90} else 7, campaign, link_id


def tag_filter(request):
    value = request.GET.get("tag", "")
    return int(value) if value.isascii() and value.isdigit() and 0 < int(value) < 2**63 else None


@login_required
@require_GET
def dashboard(request):
    workspace = current_workspace(request)
    days, campaign, link_id = report_filters(request)
    data = analytics(workspace, days, campaign, link_id, tag=tag_filter(request))
    return render(
        request,
        "links/dashboard.html",
        {
            "report": data,
            "campaigns": Campaign.objects.filter(workspace=workspace),
            "selected_campaign": campaign,
            "selected_days": days,
            "tags": Tag.objects.filter(workspace=workspace),
            "selected_tag": tag_filter(request),
        },
    )


@login_required
@require_GET
def analytics_data(request):
    return JsonResponse(
        analytics(current_workspace(request), *report_filters(request), tag=tag_filter(request))
    )


@login_required
@user_passes_test(lambda user: user.is_staff)
@require_GET
def platform_analytics(request):
    days, _, _ = report_filters(request)
    return render(
        request,
        "links/platform.html",
        {
            "report": analytics(None, days, platform=True),
            "pending": ClickEvent.objects.filter(processed_at__isnull=True).count(),
            "failed": ClickEvent.objects.filter(processed_at__isnull=True, retry_count__gte=5).count(),
            "audit": AuditLog.objects.select_related("actor", "link").order_by("-created_at")[:30],
            "geolocation": geolocation_status(),
        },
    )
