from django.conf import settings

from links.models import PlatformSettings


def policy():
    return PlatformSettings.objects.first() or PlatformSettings(
        creation_rate_limit=settings.CREATE_RATE_LIMIT,
        password_rate_limit=settings.PASSWORD_RATE_LIMIT,
        event_retention_days=settings.EVENT_RETENTION_DAYS,
    )
