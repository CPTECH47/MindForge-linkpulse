"""Register the feature-owned administration modules."""

from django.contrib import admin

from . import analytics, management, moderation, sharing  # noqa: F401
from .moderation import moderate as moderate

admin.site.site_header = "LinkPulse administration"
