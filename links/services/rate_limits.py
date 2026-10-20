import time

from django.db import transaction
from django.db.models import F

from links.models import RateLimitBucket


def consume(key, limit, seconds=60):
    """An atomic conditional update shared by every web worker."""
    window = int(time.time()) // seconds
    with transaction.atomic():
        bucket, _ = RateLimitBucket.objects.get_or_create(key=key, window=window)
        allowed = RateLimitBucket.objects.filter(pk=bucket.pk, count__lt=limit).update(count=F("count") + 1)
    return bool(allowed)
