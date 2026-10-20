from django.core.management.base import BaseCommand

from links.models import ClickEvent


class Command(BaseCommand):
    help = "Explicitly retry events whose enrichment exhausted five attempts."

    def handle(self, *args, **options):
        count = ClickEvent.objects.filter(processed_at__isnull=True, retry_count__gte=5).update(
            retry_count=0, next_retry_at=None, error_code=""
        )
        self.stdout.write(f"Queued {count} events for retry.")
