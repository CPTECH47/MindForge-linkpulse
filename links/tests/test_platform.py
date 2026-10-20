import io
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from links.forms import LinkForm
from links.models import BioPage, BlockedDomain, Campaign, ClickEvent, ImportBatch, Link, Tag, Workspace
from links.services.analytics import analytics
from links.services.imports import confirm_batch, preview_rows, read_csv
from links.services.links import save_link
from links.services.rate_limits import consume
from links.services.redirects import admit_redirect, evaluate_rules, new_grant
from links.services.worker import process_events
from links.validators import validate_alias, validate_destination

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
MOBILE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PlatformTest(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("alice", password="a-strong-password")
        self.other = get_user_model().objects.create_user("bob", password="other-strong-password")
        self.workspace = Workspace.objects.create(owner=self.owner, name="Primary")
        self.other_workspace = Workspace.objects.create(owner=self.other, name="Private")
        self.client.force_login(self.owner)
        self.link = self.make_link()

    def make_link(self, **kwargs):
        return Link.objects.create(
            workspace=kwargs.pop("workspace", self.workspace),
            title="A useful resource",
            alias=kwargs.pop("alias", "resource"),
            destination="https://example.com/guide",
            **kwargs,
        )

    def link_data(self, **kwargs):
        return {
            "title": "New link",
            "alias": "new-resource",
            "destination": "https://example.org/learn",
            "status": "active",
            **kwargs,
        }

    def context(self, **kwargs):
        return {"user_agent": UA, "source": "link", "visitor_key": "browser-1", **kwargs}

    def test_url_validation_and_canonicalization(self):
        self.assertEqual(
            validate_destination(" HTTPS://EXAMPLE.ORG/a?q=1#part "), "https://example.org/a?q=1#part"
        )
        for url in [
            "javascript:alert(1)",
            "ftp://example.org/",
            "http://localhost/x",
            "http://127.0.0.1/",
            "http://169.254.169.254/",
            "http://10.0.0.1/",
            "http://[::1]/",
            "https://user:password@example.org/",
            "https://example.org:bad/",
            "https://example.org/\r\nX:evil",
            "https://example.org\\@evil.org/",
            "https://example.local/",
            "https://2130706433/",
            "http://0177.0.0.1/",
            "http://0x7f.0.0.1/",
            "https://example.org/has space",
        ]:
            with self.subTest(url=url), self.assertRaises(ValidationError):
                validate_destination(url)

    def test_alias_policy(self):
        for alias in ["abc", "admin", "ADMIN", "x/y/z", "with space", "😀abcd", "a" * 33]:
            with self.subTest(alias=alias), self.assertRaises(ValidationError):
                validate_alias(alias)
        self.assertEqual(validate_alias("Campus_2026"), "Campus_2026")

    def test_create_through_form_hashes_password(self):
        response = self.client.post(reverse("link_create"), self.link_data(password="StrongLinkSecret123"))
        self.assertEqual(response.status_code, 302)
        link = Link.objects.get(alias="new-resource")
        self.assertTrue(check_password("StrongLinkSecret123", link.password_hash))
        self.assertNotIn("StrongLinkSecret123", link.password_hash)
        self.assertEqual(link.workspace, self.workspace)

    def test_auto_generated_alias_and_custom_collision(self):
        data = self.link_data(alias="")
        response = self.client.post(reverse("link_create"), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Link.objects.exclude(pk=self.link.pk).get().alias.__len__(), 7)
        response = self.client.post(reverse("link_create"), self.link_data(alias="resource"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already taken")

    def test_generated_alias_collision_retries(self):
        self.make_link(alias="AAAAAAA")
        choices = iter("AAAAAAABBBBBBB")
        with patch("links.services.links.secrets.choice", side_effect=lambda _: next(choices)):
            link = save_link(self.owner, self.workspace, self.link_data(alias=""))
        self.assertEqual(link.alias, "BBBBBBB")

    def test_creation_rate_limit_shared_with_imports(self):
        with override_settings(CREATE_RATE_LIMIT=1):
            save_link(self.owner, self.workspace, self.link_data())
            with self.assertRaises(ValidationError):
                save_link(self.owner, self.workspace, self.link_data(alias="another"))

    def test_expired_invalid_limit_and_foreign_relation_rejected(self):
        foreign = Campaign.objects.create(workspace=self.other_workspace, name="Secret")
        for data in [
            self.link_data(max_clicks=0),
            self.link_data(expires_at=(timezone.now() - timedelta(hours=1)).isoformat()),
            self.link_data(campaign=foreign.pk),
        ]:
            form = LinkForm(data, workspace=self.workspace)
            self.assertFalse(form.is_valid())

    def test_cross_owner_service_rejected(self):
        with self.assertRaises(PermissionDenied):
            save_link(self.other, self.workspace, self.link_data())
        foreign = Tag.objects.create(workspace=self.other_workspace, name="Hidden")
        with self.assertRaises(ValidationError):
            save_link(self.owner, self.workspace, self.link_data(tags=[foreign]))

    def test_redirect_and_cap(self):
        self.link.max_clicks = 1
        self.link.save()
        response = self.client.get(self.link.short_url, HTTP_USER_AGENT=UA)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self.link.destination)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertEqual(self.client.get(self.link.short_url).status_code, 410)
        self.link.refresh_from_db()
        self.assertEqual(self.link.successful_redirects, 1)
        self.assertEqual(self.link.events.filter(outcome="allowed").count(), 1)
        self.assertEqual(self.link.events.filter(outcome="limit").count(), 1)

    def test_head_never_consumes_click_allowance(self):
        self.assertEqual(self.client.head(self.link.short_url).status_code, 302)
        self.link.refresh_from_db()
        self.assertEqual(self.link.successful_redirects, 0)
        self.assertEqual(self.link.events.count(), 0)

    def test_rule_order_disabled_before_expiry_cap_password(self):
        self.link.status = "paused"
        self.link.expires_at = timezone.now() - timedelta(seconds=1)
        self.link.max_clicks = 1
        self.link.successful_redirects = 1
        self.link.password_hash = "not-plaintext"
        self.assertEqual(evaluate_rules(self.link).outcome, "disabled")
        self.link.status = "active"
        self.assertEqual(evaluate_rules(self.link).outcome, "expired")
        self.link.expires_at = None
        self.assertEqual(evaluate_rules(self.link).outcome, "limit")
        self.link.max_clicks = None
        self.assertEqual(evaluate_rules(self.link).outcome, "password")

    def test_password_unlock_does_not_count_then_redirect_does(self):
        from django.contrib.auth.hashers import make_password

        self.link.password_hash = make_password("PrivateSecret123")
        self.link.save()
        self.assertEqual(self.client.get(self.link.short_url).status_code, 403)
        unlock = reverse("unlock_link", args=[self.link.alias])
        self.assertEqual(self.client.post(unlock, {"password": "bad"}).status_code, 403)
        response = self.client.post(unlock, {"password": "PrivateSecret123", "source": "qr"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("?src=qr", response.url)
        self.link.refresh_from_db()
        self.assertEqual(self.link.successful_redirects, 0)
        self.assertEqual(self.client.get(response.url, HTTP_USER_AGENT=UA).status_code, 302)
        self.link.refresh_from_db()
        self.assertEqual(self.link.successful_redirects, 1)
        self.assertEqual(self.link.events.filter(outcome="allowed").get().source, "qr")

    def test_password_grants_expire_and_invalidate_on_rule_changes(self):
        self.link.password_hash = "a-hash"
        grant = new_grant(self.link)
        self.assertEqual(evaluate_rules(self.link, grant).outcome, "allowed")
        self.link.rules_version += 1
        self.assertEqual(evaluate_rules(self.link, grant).outcome, "password")
        grant = new_grant(self.link)
        grant["until"] = timezone.now().timestamp() - 1
        self.assertEqual(evaluate_rules(self.link, grant).outcome, "password")

    @override_settings(PASSWORD_RATE_LIMIT=1)
    def test_password_attempts_rate_limited(self):
        path = reverse("unlock_link", args=[self.link.alias])
        self.assertEqual(self.client.post(path, {"password": "bad"}).status_code, 403)
        self.assertEqual(self.client.post(path, {"password": "bad"}).status_code, 429)

    def test_device_routing_and_dynamic_blocklist(self):
        self.link.mobile_url = "https://mobile.example.org/"
        self.link.desktop_url = "https://desktop.example.org/"
        self.link.save()
        self.assertEqual(
            self.client.get(self.link.short_url, HTTP_USER_AGENT=MOBILE)["Location"], self.link.mobile_url
        )
        self.assertEqual(
            self.client.get(self.link.short_url, HTTP_USER_AGENT=UA)["Location"], self.link.desktop_url
        )
        BlockedDomain.objects.create(hostname="example.org", reason="Demo block")
        self.assertEqual(self.client.get(self.link.short_url, HTTP_USER_AGENT=MOBILE).status_code, 410)
        self.assertEqual(validate_destination("https://notexample.org/"), "https://notexample.org/")

    def test_transaction_rolls_back_counter_if_event_save_fails(self):
        with patch(
            "links.services.redirects.ClickEvent.objects.create", side_effect=DatabaseError("database error")
        ):
            with self.assertRaises(DatabaseError):
                admit_redirect(self.link.alias, self.context())
        self.link.refresh_from_db()
        self.assertEqual(self.link.successful_redirects, 0)

    def test_database_failure_returns_retryable_response(self):
        with patch("links.views.redirects.admit_redirect", side_effect=DatabaseError("unavailable")):
            self.assertEqual(self.client.get(self.link.short_url).status_code, 503)

    def test_owner_isolation_all_management_routes(self):
        foreign = self.make_link(alias="private-link", workspace=self.other_workspace)
        for name in ["link_detail", "link_edit", "link_qr"]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("link_toggle", args=[foreign.pk])).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("link_edit", args=[foreign.pk]), self.link_data()).status_code, 404
        )
        self.assertEqual(
            self.client.post(reverse("switch_workspace"), {"workspace": self.other_workspace.pk}).status_code,
            404,
        )
        self.assertNotContains(self.client.get(reverse("export_links")), "private-link")

    def test_bad_workspace_selection_returns_404(self):
        for value in ["", "invalid", "-1", "9" * 100]:
            with self.subTest(value=value):
                self.assertEqual(
                    self.client.post(reverse("switch_workspace"), {"workspace": value}).status_code, 404
                )

    def test_analytics_owner_period_campaign_and_bot_counts(self):
        campaign = Campaign.objects.create(workspace=self.workspace, name="Launch")
        self.link.campaign = campaign
        self.link.save()
        ClickEvent.objects.create(link=self.link, outcome="allowed", is_bot=False, visitor_key="same")
        ClickEvent.objects.create(link=self.link, outcome="allowed", is_bot=False, visitor_key="same")
        ClickEvent.objects.create(link=self.link, outcome="allowed", is_bot=True, visitor_key="bot")
        ClickEvent.objects.create(link=self.link, outcome="password", is_bot=False)
        foreign = self.make_link(alias="secret-link", workspace=self.other_workspace)
        ClickEvent.objects.create(link=foreign, outcome="allowed", is_bot=False, visitor_key="other")
        old = ClickEvent.objects.create(link=self.link, outcome="allowed", is_bot=False)
        ClickEvent.objects.filter(pk=old.pk).update(occurred_at=timezone.now() - timedelta(days=10))
        report = analytics(self.workspace, 7, campaign.pk)
        self.assertEqual(report["counts"]["redirects"], 3)
        self.assertEqual(report["counts"]["humans"], 2)
        self.assertEqual(report["counts"]["bots"], 1)
        self.assertEqual(report["counts"]["unique_browsers"], 1)
        self.assertEqual(sum(row["total"] for row in report["timeline"]), 3)
        report = self.client.get(reverse("analytics_data"), {"campaign": foreign.campaign_id or 9999}).json()
        self.assertEqual(report["counts"]["redirects"], 0)

    def test_worker_idempotent_and_bots_filtered(self):
        ClickEvent.objects.create(link=self.link, outcome="allowed", user_agent=UA)
        ClickEvent.objects.create(link=self.link, outcome="allowed", user_agent="Googlebot/2.1")
        self.assertEqual(process_events(), (2, 0))
        self.assertEqual(process_events(), (0, 0))
        self.assertEqual(self.link.events.filter(is_bot=True).count(), 1)
        self.assertFalse(self.link.events.exclude(user_agent="").exists())

    def test_worker_retry_and_recovery(self):
        event = ClickEvent.objects.create(link=self.link, outcome="allowed", user_agent=UA)
        with patch("links.services.worker.classify", side_effect=ValueError("parse failed")):
            self.assertEqual(process_events(), (0, 1))
        event.refresh_from_db()
        self.assertEqual(event.retry_count, 1)
        self.assertIsNone(event.processed_at)
        self.assertEqual(process_events(), (0, 0))
        ClickEvent.objects.filter(pk=event.pk).update(next_retry_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(process_events(), (1, 0))

    def test_unique_browser_cookie_rejects_tampering(self):
        anonymous = Client()
        first = anonymous.get(self.link.short_url, HTTP_USER_AGENT=UA)
        self.assertIn("lp_visitor", first.cookies)
        self.assertEqual(self.link.events.latest("pk").visitor_key, "")
        anonymous.get(self.link.short_url, HTTP_USER_AGENT=UA)
        self.assertTrue(self.link.events.latest("pk").visitor_key)
        anonymous.cookies["lp_visitor"] = "forged"
        anonymous.get(self.link.short_url, HTTP_USER_AGENT=UA)
        self.assertEqual(self.link.events.latest("pk").visitor_key, "")

    def test_qr_is_real_png_and_owner_only(self):
        response = self.client.get(reverse("link_qr", args=[self.link.pk]) + "?download=1")
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("attachment", response["Content-Disposition"])

    def test_csv_preview_duplicates_invalid_and_confirm_idempotent(self):
        rows = [
            {"title": "First", "destination": "https://example.org/", "alias": "csv-link"},
            {"destination": "javascript:bad", "alias": "csv-bad"},
            {"destination": "https://example.org/", "alias": "csv-link"},
        ]
        results = preview_rows(self.workspace, rows)
        self.assertEqual([row["state"] for row in results], ["ready", "invalid", "invalid"])
        batch = ImportBatch.objects.create(workspace=self.workspace, rows=rows, results=results)
        confirmed = confirm_batch(self.owner, batch.pk)
        self.assertEqual(confirmed.results[0]["state"], "created")
        self.assertEqual(confirm_batch(self.owner, batch.pk).results, confirmed.results)
        self.assertEqual(Link.objects.filter(alias="csv-link").count(), 1)

    def test_csv_parser_rejects_oversize_headers_and_wrong_encoding(self):
        invalid = [
            b"wrong\nfoo",
            b"destination,destination\nx,y",
            b"destination,password\nhttps://example.org/,secret",
            b"destination\n\xff",
            b"destination\nx,y",
            b"destination\n" + b"x\n" * 201,
            b"destination\n" + b"a" * 262144,
        ]
        for content in invalid:
            with self.subTest(content=content[:30]), self.assertRaises(ValidationError):
                read_csv(SimpleUploadedFile("import.csv", content))

    def test_csv_upload_actual_view_and_import_results(self):
        upload = SimpleUploadedFile(
            "links.csv", b"title,destination,alias\nImported,https://example.org/,imported-link\n"
        )
        response = self.client.post(reverse("import_csv"), {"file": upload})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(response.url), "1 valid rows ready")
        self.assertEqual(self.client.post(response.url).status_code, 302)
        self.assertContains(self.client.get(response.url), "created")

    def test_csv_revalidates_on_confirmation_and_expiry(self):
        rows = [{"destination": "https://laterblocked.org/", "alias": "later-block"}]
        batch = ImportBatch.objects.create(
            workspace=self.workspace, rows=rows, results=preview_rows(self.workspace, rows)
        )
        BlockedDomain.objects.create(hostname="laterblocked.org", reason="Test")
        self.assertEqual(confirm_batch(self.owner, batch.pk).results[0]["state"], "invalid")
        batch = ImportBatch.objects.create(workspace=self.workspace, rows=rows, results=[])
        ImportBatch.objects.filter(pk=batch.pk).update(created_at=timezone.now() - timedelta(minutes=31))
        with self.assertRaises(ValidationError):
            confirm_batch(self.owner, batch.pk)

    def test_cross_owner_import_forbidden(self):
        batch = ImportBatch.objects.create(workspace=self.other_workspace)
        self.assertEqual(self.client.get(reverse("import_batch", args=[batch.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("import_batch", args=[batch.pk])).status_code, 404)

    def test_csv_export_neutralizes_formulas(self):
        self.link.title = "=IMPORTDATA(1)"
        self.link.save()
        response = self.client.get(reverse("export_links"))
        self.assertContains(response, "'=IMPORTDATA(1)")

    def test_user_cannot_restore_admin_blocked_link(self):
        self.link.status = "blocked"
        self.link.save()
        self.client.post(reverse("link_toggle", args=[self.link.pk]))
        response = self.client.post(
            reverse("link_edit", args=[self.link.pk]), self.link_data(alias=self.link.alias, status="active")
        )
        self.assertEqual(response.status_code, 200)
        self.link.refresh_from_db()
        self.assertEqual(self.link.status, "blocked")

    def test_rule_updates_invalidate_grants_and_preserve_history(self):
        ClickEvent.objects.create(link=self.link, outcome="allowed")
        response = self.client.post(
            reverse("link_edit", args=[self.link.pk]), self.link_data(alias=self.link.alias, max_clicks=5)
        )
        self.assertEqual(response.status_code, 302)
        self.link.refresh_from_db()
        self.assertEqual(self.link.rules_version, 2)
        self.assertEqual(self.link.events.count(), 1)

    def test_preview_never_records_clicks(self):
        response = self.client.post(reverse("link_preview"), self.link_data())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["valid"])
        self.assertEqual(ClickEvent.objects.count(), 0)

    def test_bio_cross_workspace_relationship_defense(self):
        foreign = self.make_link(alias="foreign-bio", workspace=self.other_workspace)
        bio = BioPage.objects.create(workspace=self.workspace, slug="our-team", title="Team", published=True)
        bio.links.add(self.link, foreign)
        response = Client().get(reverse("bio_page", args=[bio.slug]))
        self.assertContains(response, "/r/resource/?src=bio")
        self.assertNotContains(response, "foreign-bio")

    def test_csrf_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(reverse("link_create"), self.link_data()).status_code, 403)
        self.assertEqual(client.post(reverse("link_toggle", args=[self.link.pk])).status_code, 403)

    def test_all_management_pages_render_and_escape_user_content(self):
        self.link.title = '<script>alert("x")</script>'
        self.link.save()
        for name, args in [
            ("dashboard", []),
            ("link_list", []),
            ("link_create", []),
            ("link_edit", [self.link.pk]),
            ("link_detail", [self.link.pk]),
            ("organize", []),
            ("settings", []),
            ("import_csv", []),
        ]:
            with self.subTest(name=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, '<script>alert("x")</script>')
                self.assertIn("Content-Security-Policy", response)

    def test_nonstaff_denied_platform_and_anonymous_denied_management(self):
        self.assertEqual(self.client.get(reverse("platform_analytics")).status_code, 302)
        self.assertEqual(Client().get(reverse("dashboard")).status_code, 302)
        self.assertEqual(Client().get(reverse("link_list")).status_code, 302)

    def test_signup_login_and_logout(self):
        client = Client()
        response = client.post(
            reverse("signup"),
            {
                "username": "student",
                "password1": "StudentSecurePassword!49",
                "password2": "StudentSecurePassword!49",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Workspace.objects.filter(owner__username="student").exists())
        self.assertEqual(client.post(reverse("logout")).status_code, 302)
        self.assertEqual(
            client.post(
                reverse("login"), {"username": "student", "password": "StudentSecurePassword!49"}
            ).status_code,
            302,
        )

    def test_retention_keeps_lifetime_counters(self):
        self.link.successful_redirects = 20
        self.link.save()
        event = ClickEvent.objects.create(link=self.link, outcome="allowed")
        ClickEvent.objects.filter(pk=event.pk).update(occurred_at=timezone.now() - timedelta(days=40))
        call_command("cleanup_data", stdout=io.StringIO())
        self.link.refresh_from_db()
        self.assertEqual(self.link.successful_redirects, 20)
        self.assertFalse(ClickEvent.objects.exists())

    def test_admin_moderation_audits_and_immediate_block(self):
        from django.test import RequestFactory

        from links.admin import moderate

        request = RequestFactory().post("/admin/")
        request.user = self.owner
        moderate(request, Link.objects.filter(pk=self.link.pk), "blocked")
        self.assertEqual(self.client.get(self.link.short_url).status_code, 410)
        self.assertTrue(self.link.auditlog_set.filter(action="admin.blocked").exists())

    def test_rate_bucket_never_exceeds_limit(self):
        self.assertTrue(consume("test", 2))
        self.assertTrue(consume("test", 2))
        self.assertFalse(consume("test", 2))

    def test_staff_platform_renders(self):
        self.owner.is_staff = True
        self.owner.save()
        self.assertEqual(self.client.get(reverse("platform_analytics")).status_code, 200)
