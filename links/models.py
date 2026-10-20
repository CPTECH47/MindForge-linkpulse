import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse


class Workspace(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspaces")
    name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="workspace_owner_name")]

    def __str__(self):
        return self.name


class WorkspaceGroup(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    name = models.CharField(max_length=80)
    archived = models.BooleanField(default=False)

    class Meta:
        abstract = True

    def __str__(self):
        return self.name


class Campaign(WorkspaceGroup):
    description = models.CharField(max_length=240, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "name"], name="campaign_workspace_name")]


class Folder(WorkspaceGroup):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "name"], name="folder_workspace_name")]


class Tag(WorkspaceGroup):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "name"], name="tag_workspace_name")]


class Link(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        BLOCKED = "blocked", "Blocked by administrator"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="links")
    campaign = models.ForeignKey(
        Campaign, null=True, blank=True, on_delete=models.PROTECT, related_name="links"
    )
    folder = models.ForeignKey(Folder, null=True, blank=True, on_delete=models.PROTECT, related_name="links")
    tags = models.ManyToManyField(Tag, blank=True, related_name="links")
    title = models.CharField(max_length=120)
    alias = models.CharField(max_length=32, unique=True)
    destination = models.URLField(max_length=2048)
    mobile_url = models.URLField(max_length=2048, blank=True)
    desktop_url = models.URLField(max_length=2048, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    expires_at = models.DateTimeField(null=True, blank=True)
    max_clicks = models.PositiveIntegerField(null=True, blank=True)
    successful_redirects = models.PositiveBigIntegerField(default=0, editable=False)
    password_hash = models.CharField(max_length=256, blank=True, editable=False)
    rules_version = models.PositiveIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["workspace", "created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_clicks__isnull=True) | models.Q(max_clicks__gte=1),
                name="positive_click_limit",
            )
        ]

    @property
    def short_url(self):
        return settings.PUBLIC_BASE_URL + reverse("redirect_link", args=[self.alias])

    def __str__(self):
        return f"{self.alias}: {self.title}"


class ClickEvent(models.Model):
    link = models.ForeignKey(Link, on_delete=models.CASCADE, related_name="events")
    occurred_at = models.DateTimeField(auto_now_add=True)
    outcome = models.CharField(max_length=24)
    source = models.CharField(max_length=10, default="link")
    referrer_host = models.CharField(max_length=253, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    visitor_key = models.CharField(max_length=64, blank=True)
    country = models.CharField(max_length=2, blank=True)
    browser = models.CharField(max_length=80, blank=True)
    device = models.CharField(max_length=16, blank=True)
    is_bot = models.BooleanField(null=True, default=None)
    processed_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["link", "occurred_at"]),
            models.Index(fields=["processed_at", "next_retry_at"]),
        ]


class BlockedDomain(models.Model):
    hostname = models.CharField(max_length=253, unique=True)
    reason = models.CharField(max_length=240)
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return self.hostname


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    link = models.ForeignKey(Link, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)


class RateLimitBucket(models.Model):
    key = models.CharField(max_length=128)
    window = models.BigIntegerField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["key", "window"], name="rate_key_window")]


class ImportBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    rows = models.JSONField(default=list)
    results = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class BioPage(models.Model):
    workspace = models.OneToOneField(Workspace, on_delete=models.CASCADE)
    slug = models.SlugField(max_length=50, unique=True)
    title = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True)
    published = models.BooleanField(default=False)
    links = models.ManyToManyField(Link, blank=True)


class PlatformSettings(models.Model):
    """Editable operational policy; credentials stay in environment variables."""

    creation_rate_limit = models.PositiveIntegerField(default=100)
    password_rate_limit = models.PositiveIntegerField(default=10)
    event_retention_days = models.PositiveIntegerField(default=30)
    signup_enabled = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return "Platform settings"

    class Meta:
        verbose_name_plural = "Platform settings"
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="single_platform_policy"),
            models.CheckConstraint(
                condition=models.Q(creation_rate_limit__gte=1, creation_rate_limit__lte=10000),
                name="bounded_creation_policy",
            ),
            models.CheckConstraint(
                condition=models.Q(password_rate_limit__gte=1, password_rate_limit__lte=100),
                name="bounded_password_policy",
            ),
            models.CheckConstraint(
                condition=models.Q(event_retention_days__gte=1, event_retention_days__lte=3650),
                name="bounded_retention_policy",
            ),
        ]
