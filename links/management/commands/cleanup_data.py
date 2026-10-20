import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from links.models import ClickEvent, ImportBatch, RateLimitBucket
from links.services.policy import policy


class Command(BaseCommand):
    help = "Delete old events and temporary imports/rate buckets. Lifetime redirect counters are retained."

    def handle(self, *args, **options):
        count, _ = ClickEvent.objects.filter(
            occurred_at__lt=timezone.now() - timedelta(days=policy().event_retention_days)
        ).delete()
        ImportBatch.objects.filter(created_at__lt=timezone.now() - timedelta(days=1)).delete()
        RateLimitBucket.objects.filter(window__lt=int(time.time()) // 60 - 1440).delete()
        self.stdout.write(f"Removed {count} old events; lifetime link counters retained.")
