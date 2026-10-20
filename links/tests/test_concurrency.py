from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase

from links.models import ClickEvent, Link, Workspace
from links.services.rate_limits import consume
from links.services.redirects import admit_redirect
from links.services.worker import process_events


@skipUnless(
    connection.vendor == "postgresql",
    "Concurrency guarantees require PostgreSQL; CI runs this suite against PostgreSQL.",
)
class PostgreSQLConcurrencyTest(TransactionTestCase):
    def setUp(self):
        owner = get_user_model().objects.create_user("concurrent")
        workspace = Workspace.objects.create(owner=owner, name="Test")
        self.link = Link.objects.create(
            workspace=workspace,
            title="One remaining click",
            alias="last-click",
            destination="https://example.org/",
            max_clicks=1,
        )

    def run_concurrently(self, function, workers=8):
        barrier = Barrier(workers)

        def task(_):
            close_old_connections()
            try:
                barrier.wait(timeout=20)
                return function()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=workers) as executor:
            return list(executor.map(task, range(workers)))

    def test_eight_requests_for_last_click_admit_exactly_one(self):
        outcomes = self.run_concurrently(
            lambda: admit_redirect("last-click", {"user_agent": "Mozilla/5.0", "source": "link"})[1].outcome
        )
        self.assertEqual(outcomes.count("allowed"), 1)
        self.assertEqual(outcomes.count("limit"), 7)
        self.link.refresh_from_db()
        self.assertEqual(self.link.successful_redirects, 1)
        self.assertEqual(ClickEvent.objects.filter(outcome="allowed").count(), 1)
        self.assertEqual(ClickEvent.objects.count(), 8)

    def test_shared_rate_limit_is_atomic(self):
        outcomes = self.run_concurrently(lambda: consume("concurrent-bucket", 3))
        self.assertEqual(outcomes.count(True), 3)

    def test_worker_claims_do_not_process_rows_twice(self):
        for _ in range(20):
            ClickEvent.objects.create(link=self.link, outcome="allowed", user_agent="Mozilla/5.0")
        outcomes = self.run_concurrently(lambda: process_events(), workers=4)
        self.assertEqual(sum(value[0] for value in outcomes), 20)
        self.assertEqual(ClickEvent.objects.filter(processed_at__isnull=False).count(), 20)
