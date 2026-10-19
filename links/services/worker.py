import logging
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

from links.models import ClickEvent
from links.services.tracking import classify

logger = logging.getLogger(__name__)


def process_events(limit=100):
    processed = 0
    failed = 0
    now = timezone.now()
    candidates = ClickEvent.objects.filter(processed_at__isnull=True, retry_count__lt=5).filter(
        next_retry_at__isnull=True
    ) | ClickEvent.objects.filter(processed_at__isnull=True, retry_count__lt=5, next_retry_at__lte=now)
    ids = list(candidates.order_by("pk").values_list("pk", flat=True)[:limit])
    for event_id in ids:
        with transaction.atomic():
            query = ClickEvent.objects.filter(pk=event_id, processed_at__isnull=True, retry_count__lt=5)
            if connection.features.has_select_for_update_skip_locked:
                query = query.select_for_update(skip_locked=True)
            else:
                query = query.select_for_update()
            event = query.first()
            if event is None or (event.next_retry_at and event.next_retry_at > timezone.now()):
                continue
            try:
                fields = classify(event.user_agent)
            except Exception:
                event.retry_count += 1
                event.error_code = "ENRICHMENT_FAILED"
                event.next_retry_at = now + timedelta(seconds=2**event.retry_count)
                event.save(update_fields=["retry_count", "error_code", "next_retry_at"])
                logger.exception("Enrichment failed for event %s", event.pk)
                failed += 1
            else:
                for key, value in fields.items():
                    setattr(event, key, value)
                event.processed_at = timezone.now()
                event.user_agent = ""  # Remove raw metadata after enrichment.
                event.error_code = ""
                event.next_retry_at = None
                event.save(
                    update_fields=[*fields, "processed_at", "user_agent", "error_code", "next_retry_at"]
                )
                processed += 1
    return processed, failed
