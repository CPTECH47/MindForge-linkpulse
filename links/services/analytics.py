from datetime import timedelta

from django.db.models import Count, F, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from links.models import ClickEvent, Link


def analytics(workspace, days=7, campaign=None, link_id=None, platform=False, tag=None):
    links = Link.objects.all() if platform else Link.objects.filter(workspace=workspace)
    if campaign:
        links = links.filter(campaign_id=campaign)
    if link_id:
        links = links.filter(pk=link_id)
    if tag:
        links = links.filter(tags__pk=tag)
    start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    events = ClickEvent.objects.filter(link__in=links, occurred_at__gte=start)
    allowed = events.filter(outcome="allowed")
    human = allowed.filter(is_bot=False)
    identified = human.exclude(visitor_key="")
    counts = events.aggregate(
        attempts=Count("pk"),
        redirects=Count("pk", filter=Q(outcome="allowed")),
        blocked=Count("pk", filter=~Q(outcome="allowed")),
        pending=Count("pk", filter=Q(processed_at__isnull=True)),
        bots=Count("pk", filter=Q(outcome="allowed", is_bot=True)),
        humans=Count("pk", filter=Q(outcome="allowed", is_bot=False)),
    )
    counts.update(
        links=links.count(),
        unique_browsers=identified.values("visitor_key").distinct().count(),
        identification_coverage=round(100 * identified.count() / counts["humans"]) if counts["humans"] else 0,
    )
    daily = {
        row["day"].isoformat(): row["total"]
        for row in allowed.annotate(day=TruncDate("occurred_at")).values("day").annotate(total=Count("pk"))
    }
    today = timezone.now().date()
    timeline = [
        {
            "day": (today - timedelta(days=offset)).isoformat(),
            "total": daily.get((today - timedelta(days=offset)).isoformat(), 0),
        }
        for offset in reversed(range(days))
    ]

    def breakdown(field):
        return list(human.values(field).annotate(total=Count("pk")).order_by("-total")[:10])

    return {
        "counts": counts,
        "timeline": timeline,
        "devices": breakdown("device"),
        "browsers": breakdown("browser"),
        "referrers": breakdown("referrer_host"),
        "countries": breakdown("country"),
        "sources": list(allowed.values("source").annotate(total=Count("pk")).order_by("-total")),
        "top_links": list(
            allowed.values("link__id", "link__title", "link__alias")
            .annotate(total=Count("pk"))
            .order_by("-total")[:8]
        ),
        "campaigns": list(
            allowed.values("link__campaign__name").annotate(total=Count("pk")).order_by("-total")[:10]
        ),
        "tags": list(
            allowed.exclude(link__tags__isnull=True)
            .values("link__tags__id", "link__tags__name")
            .annotate(total=Count("pk", distinct=True))
            .order_by("-total")[:10]
        ),
        "alerts": list(
            links.filter(
                Q(status__in=["paused", "blocked"])
                | Q(expires_at__lte=timezone.now())
                | Q(max_clicks__isnull=False, successful_redirects__gte=F("max_clicks"))
            ).values("id", "title", "alias", "status")[:8]
        ),
        "generated_at": timezone.now().isoformat(),
        "days": days,
    }
