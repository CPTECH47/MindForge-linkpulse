import random
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from links.models import BioPage, Campaign, ClickEvent, Folder, Link, Tag, Workspace


class Command(BaseCommand):
    help = "Create clearly labeled synthetic demo data. Never changes an existing user's password."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="demo")

    @transaction.atomic
    def handle(self, *args, **options):
        user, created = get_user_model().objects.get_or_create(username=options["username"])
        if created:
            password = secrets.token_urlsafe(15)
            user.set_password(password)
            user.save()
            self.stdout.write(f"Created demo account: {user.username}\nGenerated password: {password}")
        workspace, _ = Workspace.objects.get_or_create(owner=user, name="Demo · synthetic data")
        if workspace.links.exists():
            self.stdout.write("Demo data already exists; nothing changed.")
            return
        campaign = Campaign.objects.create(
            workspace=workspace, name="Campus launch", description="Synthetic demo campaign"
        )
        folder = Folder.objects.create(workspace=workspace, name="Learning resources")
        tag = Tag.objects.create(workspace=workspace, name="demo")
        rng = random.Random(42)
        definitions = [
            ("Python learning hub", "learn-python", "https://docs.python.org/3/", {}),
            ("Django workshop", "django-workshop", "https://docs.djangoproject.com/en/5.2/", {}),
            (
                "Private team handbook",
                "team-guide",
                "https://www.python.org/about/",
                {"password_hash": make_password("CampusDemo2026!")},
            ),
            (
                "Limited workshop invitation",
                "workshop-10",
                "https://www.djangoproject.com/",
                {"max_clicks": 10},
            ),
            ("Archived announcement", "archived-news", "https://www.python.org/", {"status": "paused"}),
        ]
        for index, (title, alias, destination, extra) in enumerate(definitions):
            if Link.objects.filter(alias=alias).exists():
                alias = alias + "-" + secrets.token_hex(3)
            link = Link.objects.create(
                workspace=workspace,
                campaign=campaign,
                folder=folder,
                title=title,
                alias=alias,
                destination=destination,
                **extra,
            )
            link.tags.add(tag)
            if index < 3:
                for _ in range(65 - index * 17):
                    at = timezone.now() - timedelta(hours=rng.randint(0, 160))
                    bot = rng.random() < 0.12
                    event = ClickEvent.objects.create(
                        link=link,
                        outcome="allowed",
                        source=rng.choice(["link", "link", "qr", "bio"]),
                        browser=rng.choice(["Chrome", "Firefox", "Safari"]),
                        device=rng.choice(["desktop", "mobile", "tablet"]),
                        is_bot=bot,
                        country=rng.choice(["IN", "US", "GB"]),
                        referrer_host=rng.choice(["", "www.google.com", "linkedin.com"]),
                        visitor_key=f"synthetic-browser-{rng.randint(1, 24)}",
                        processed_at=at,
                    )
                    ClickEvent.objects.filter(pk=event.pk).update(occurred_at=at)
                link.successful_redirects = link.events.count()
                link.save(update_fields=["successful_redirects"])
        slug = "campus-demo-" + str(workspace.pk)
        if BioPage.objects.filter(slug=slug).exists():
            raise CommandError("Demo bio slug is in use. Choose another demo user.")
        bio = BioPage.objects.create(
            workspace=workspace,
            slug=slug,
            title="Campus connections",
            description="Synthetic LinkPulse demonstration",
            published=True,
        )
        bio.links.set(workspace.links.all())
        self.stdout.write("Created synthetic links and events. Password-protected demo link: CampusDemo2026!")
        self.stdout.write(
            "Sign in and choose 'Demo · synthetic data'. Use createsuperuser separately for administration."
        )
