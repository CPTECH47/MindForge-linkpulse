import io
import tempfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from links.forms import LinkForm
from links.models import BioPage, Campaign, ClickEvent, Folder, Link, PlatformSettings, Tag, Workspace
from links.services.analytics import analytics
from links.services.links import save_link
from links.services.tracking import client_ip, country_for_ip, geolocation_status


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ScopeCompletionTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("owner")
        self.other = get_user_model().objects.create_user("other")
        self.admin = get_user_model().objects.create_superuser("administrator", "", "admin-secret")
        self.space = Workspace.objects.create(owner=self.owner, name="Team")
        self.foreign_space = Workspace.objects.create(owner=self.other, name="Other")
        self.campaign = Campaign.objects.create(workspace=self.space, name="Launch")
        self.folder = Folder.objects.create(workspace=self.space, name="Resources")
        self.tag = Tag.objects.create(workspace=self.space, name="Campus")
        self.link = Link.objects.create(
            workspace=self.space,
            campaign=self.campaign,
            folder=self.folder,
            title="Learning",
            alias="learning",
            destination="https://example.org/",
            successful_redirects=5,
        )
        self.link.tags.add(self.tag)
        self.client.force_login(self.owner)

    def admin_data(self, **overrides):
        return {
            "workspace": self.space.pk,
            "title": "Admin created",
            "alias": "admin-created",
            "destination": "https://example.org/",
            "status": "active",
            "tags": [self.tag.pk],
            **overrides,
        }

    def test_rename_all_group_types(self):
        for kind, group in [("campaign", self.campaign), ("folder", self.folder), ("tag", self.tag)]:
            path = reverse("group_edit", args=[kind, group.pk])
            self.assertEqual(self.client.get(path).status_code, 200)
            self.assertEqual(
                self.client.post(path, {"name": "Renamed", "description": "New notes"}).status_code, 302
            )
            group.refresh_from_db()
            self.assertEqual(group.name, "Renamed")
        self.link.refresh_from_db()
        self.assertEqual(self.link.successful_redirects, 5)
        self.assertEqual(self.link.campaign_id, self.campaign.pk)

    def test_duplicate_group_name_is_reported(self):
        Tag.objects.create(workspace=self.space, name="Existing")
        response = self.client.post(reverse("group_edit", args=["tag", self.tag.pk]), {"name": "Existing"})
        self.assertEqual(response.status_code, 200)
        self.tag.refresh_from_db()
        self.assertEqual(self.tag.name, "Campus")

    def test_archive_retains_links_but_rejects_new_assignments(self):
        path = reverse("group_edit", args=["tag", self.tag.pk])
        self.client.post(path, {"name": self.tag.name, "archived": "on"})
        self.tag.refresh_from_db()
        self.assertTrue(self.tag.archived)
        self.assertTrue(self.link.tags.filter(pk=self.tag.pk).exists())
        self.assertNotIn(self.tag, LinkForm(workspace=self.space).fields["tags"].queryset)
        self.assertIn(self.tag, LinkForm(workspace=self.space, instance=self.link).fields["tags"].queryset)
        with self.assertRaises(ValidationError):
            save_link(
                self.owner,
                self.space,
                {
                    "title": "Invalid assignment",
                    "alias": "new-tagged",
                    "destination": "https://example.org/",
                    "tags": [self.tag],
                },
            )
        self.client.post(path, {"name": self.tag.name})
        self.tag.refresh_from_db()
        self.assertFalse(self.tag.archived)

    def test_delete_used_groups_preserves_history(self):
        ClickEvent.objects.create(link=self.link, outcome="allowed")
        for kind, group in [("campaign", self.campaign), ("folder", self.folder), ("tag", self.tag)]:
            response = self.client.post(reverse("group_delete", args=[kind, group.pk]))
            self.assertEqual(response.status_code, 302)
            self.assertTrue(type(group).objects.filter(pk=group.pk).exists())
        self.assertEqual(ClickEvent.objects.count(), 1)

    def test_delete_unused_groups(self):
        for kind, model in [("campaign", Campaign), ("folder", Folder), ("tag", Tag)]:
            group = model.objects.create(workspace=self.space, name="Unused")
            response = self.client.post(reverse("group_delete", args=[kind, group.pk]))
            self.assertEqual(response.status_code, 302)
            self.assertFalse(model.objects.filter(pk=group.pk).exists())

    def test_foreign_group_edits_and_deletes_are_404(self):
        group = Tag.objects.create(workspace=self.foreign_space, name="Private")
        for route in ["group_edit", "group_delete"]:
            self.assertEqual(
                self.client.post(reverse(route, args=["tag", group.pk]), {"name": "Hacked"}).status_code, 404
            )

    def test_tag_analytics_and_combined_filters_without_double_count(self):
        second_tag = Tag.objects.create(workspace=self.space, name="Web")
        self.link.tags.add(second_tag)
        for _ in range(3):
            ClickEvent.objects.create(link=self.link, outcome="allowed", is_bot=False)
        ClickEvent.objects.create(link=self.link, outcome="password")
        old = ClickEvent.objects.create(link=self.link, outcome="allowed")
        ClickEvent.objects.filter(pk=old.pk).update(occurred_at=timezone.now() - timedelta(days=10))
        report = analytics(self.space, 7, self.campaign.pk, tag=self.tag.pk)
        self.assertEqual(report["counts"]["redirects"], 3)
        self.assertEqual([row["total"] for row in report["tags"]], [3, 3])
        self.assertEqual(len(report["top_links"]), 1)
        response = self.client.get(reverse("analytics_data"), {"tag": self.tag.pk})
        self.assertEqual(response.json()["counts"]["redirects"], 3)
        foreign_tag = Tag.objects.create(workspace=self.foreign_space, name="Private")
        self.assertEqual(
            self.client.get(reverse("analytics_data"), {"tag": foreign_tag.pk}).json()["counts"]["redirects"],
            0,
        )

    def test_tag_report_page_totals_and_archived_listing(self):
        ClickEvent.objects.create(link=self.link, outcome="allowed")
        response = self.client.get(reverse("group_edit", args=["tag", self.tag.pk]))
        self.assertEqual(response.context["period_clicks"], 1)
        self.assertEqual(response.context["clicks"], 5)
        self.assertEqual(response.context["top_links"][0].period_clicks, 1)
        self.tag.archived = True
        self.tag.save()
        response = self.client.get(reverse("organize"))
        self.assertFalse(response.context["groups"][2]["items"].exists())
        response = self.client.get(reverse("organize"), {"archived": "1"})
        self.assertEqual(response.context["groups"][2]["items"].count(), 1)

    def test_admin_creates_and_edits_foreign_owner_link(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin:links_link_add"), self.admin_data(password="SecretPassword123")
        )
        self.assertEqual(response.status_code, 302)
        link = Link.objects.get(alias="admin-created")
        self.assertTrue(link.password_hash)
        version = self.link.rules_version
        response = self.client.post(
            reverse("admin:links_link_change", args=[self.link.pk]),
            self.admin_data(
                alias=self.link.alias,
                title="Updated by admin",
                status="blocked",
                campaign=self.campaign.pk,
                folder=self.folder.pk,
            ),
        )
        self.assertEqual(response.status_code, 302)
        self.link.refresh_from_db()
        self.assertEqual(self.link.title, "Updated by admin")
        self.assertEqual(self.link.status, "blocked")
        self.assertEqual(self.link.rules_version, version + 1)
        self.assertEqual(self.link.successful_redirects, 5)
        self.assertTrue(self.link.auditlog_set.filter(action="admin.link.edited").exists())

    def test_admin_cannot_mix_workspace_relations(self):
        foreign = Tag.objects.create(workspace=self.foreign_space, name="Private")
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin:links_link_add"), self.admin_data(tags=[foreign.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Link.objects.filter(alias="admin-created").exists())

    def test_admin_preserves_counters_alias_and_workspace(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin:links_link_change", args=[self.link.pk]),
            self.admin_data(
                alias="hijack-alias",
                workspace=self.foreign_space.pk,
                successful_redirects=999,
                rules_version=999,
                title="Safe edit",
            ),
        )
        self.assertEqual(response.status_code, 302)
        self.link.refresh_from_db()
        self.assertEqual(self.link.alias, "learning")
        self.assertEqual(self.link.workspace_id, self.space.pk)
        self.assertEqual(self.link.successful_redirects, 5)
        self.assertEqual(self.link.rules_version, 2)

    def test_nonprivileged_staff_cannot_use_admin_service(self):
        self.owner.is_staff = True
        self.owner.save()
        with self.assertRaises(PermissionDenied):
            save_link(
                self.owner,
                self.space,
                {"title": "Attempt", "destination": "https://example.org/"},
                administrator=True,
            )

    def test_admin_business_records_are_editable(self):
        self.client.force_login(self.admin)
        for model, group in [("campaign", self.campaign), ("folder", self.folder), ("tag", self.tag)]:
            response = self.client.post(
                reverse(f"admin:links_{model}_change", args=[group.pk]),
                {"name": "Admin renamed", "description": "Notes", "archived": "on"},
            )
            self.assertEqual(response.status_code, 302)
            group.refresh_from_db()
            self.assertTrue(group.archived)
        response = self.client.post(
            reverse("admin:links_workspace_change", args=[self.space.pk]),
            {"name": "Renamed workspace", "owner": self.owner.pk},
        )
        self.assertEqual(response.status_code, 302)

    def test_admin_bio_validates_ownership(self):
        self.client.force_login(self.admin)
        foreign = Link.objects.create(
            workspace=self.foreign_space,
            title="Private",
            alias="private-bio",
            destination="https://example.org/",
        )
        response = self.client.post(
            reverse("admin:links_biopage_add"),
            {
                "workspace": self.space.pk,
                "slug": "my-bio",
                "title": "Bio",
                "links": [foreign.pk],
                "published": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(BioPage.objects.exists())
        response = self.client.post(
            reverse("admin:links_biopage_add"),
            {
                "workspace": self.space.pk,
                "slug": "my-bio",
                "title": "Bio",
                "links": [self.link.pk],
                "published": "on",
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_platform_policy_changes_runtime_behavior(self):
        PlatformSettings.objects.create(signup_enabled=False, creation_rate_limit=1, event_retention_days=10)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("signup")).status_code, 403)
        self.client.force_login(self.owner)
        save_link(
            self.owner,
            self.space,
            {"title": "One", "alias": "rate-one", "destination": "https://example.org/"},
        )
        with self.assertRaises(ValidationError):
            save_link(
                self.owner,
                self.space,
                {"title": "Two", "alias": "rate-two", "destination": "https://example.org/"},
            )
        event = ClickEvent.objects.create(link=self.link, outcome="allowed")
        ClickEvent.objects.filter(pk=event.pk).update(occurred_at=timezone.now() - timedelta(days=11))
        call_command("cleanup_data", stdout=io.StringIO())
        self.assertFalse(ClickEvent.objects.filter(pk=event.pk).exists())

    def test_admin_settings_screen_and_invalid_values(self):
        self.client.force_login(self.admin)
        path = reverse("admin:links_platformsettings_add")
        response = self.client.post(
            path, {"creation_rate_limit": 0, "password_rate_limit": 10000, "event_retention_days": 0}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PlatformSettings.objects.exists())
        response = self.client.post(
            path,
            {
                "creation_rate_limit": 50,
                "password_rate_limit": 5,
                "event_retention_days": 60,
                "signup_enabled": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PlatformSettings.objects.get().creation_rate_limit, 50)
        self.assertEqual(self.client.get(path).status_code, 403)

    def test_location_public_lookup_and_private_address_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "country.mmdb"
            path.write_bytes(b"test")
            reader = SimpleNamespace(
                country=lambda ip: SimpleNamespace(country=SimpleNamespace(iso_code="IN")),
                metadata=lambda: SimpleNamespace(database_type="DBIP-Country-Lite"),
            )
            with (
                override_settings(GEOIP_DATABASE=str(path)),
                patch("links.services.tracking.geo_reader", return_value=reader) as mock,
            ):
                self.assertEqual(country_for_ip("1.1.1.1"), "IN")
                self.assertTrue(geolocation_status()["ready"])
                self.assertEqual(country_for_ip("127.0.0.1"), "")
                self.assertEqual(country_for_ip("10.0.0.1"), "")
                self.assertEqual(country_for_ip("not-an-ip"), "")
                self.assertEqual(mock.call_count, 2)

    def test_location_missing_or_broken_database(self):
        with override_settings(GEOIP_DATABASE="/nonexistent/linkpulse-country.mmdb"):
            self.assertEqual(country_for_ip("8.8.8.8"), "")
            self.assertFalse(geolocation_status()["ready"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.mmdb"
            path.write_bytes(b"not a database")
            with override_settings(GEOIP_DATABASE=str(path)):
                self.assertEqual(country_for_ip("8.8.8.8"), "")
                self.assertFalse(geolocation_status()["ready"])

    def test_geo_installer_preserves_existing_database_on_bad_input(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "installed.mmdb"
            destination.write_bytes(b"existing-data")
            invalid = Path(directory) / "invalid.mmdb"
            invalid.write_bytes(b"invalid-data")
            with override_settings(GEOIP_DATABASE=str(destination)):
                with self.assertRaises(CommandError):
                    call_command("install_geoip", file=str(invalid), stdout=io.StringIO())
                self.assertEqual(destination.read_bytes(), b"existing-data")
                self.assertEqual(len(list(Path(directory).glob("*.mmdb"))), 2)

    def test_proxy_address_only_trusted_when_explicitly_enabled(self):
        request = RequestFactory().get(
            "/", REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="1.1.1.1", HTTP_X_FORWARDED_FOR="8.8.8.8"
        )
        with override_settings(TRUST_PROXY_IP=False):
            self.assertEqual(client_ip(request), "127.0.0.1")
        with override_settings(TRUST_PROXY_IP=True):
            self.assertEqual(client_ip(request), "1.1.1.1")
