import time

from django.core.management.base import BaseCommand
from django.db import DatabaseError, close_old_connections

from links.services.worker import process_events


class Command(BaseCommand):
    help = "Enrich captured clicks. Use --loop for the background worker. Safe to run multiple PostgreSQL workers."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--interval", type=float, default=2)

    def handle(self, *args, **options):
        try:
            while True:
                try:
                    processed, failed = process_events(max(1, min(options["batch_size"], 1000)))
                    if processed or failed or not options["loop"]:
                        self.stdout.write(f"Processed {processed}; failed {failed}")
                except DatabaseError:
                    if not options["loop"]:
                        raise
                    self.stderr.write("Database unavailable; worker will reconnect.")
                finally:
                    close_old_connections()
                if not options["loop"]:
                    break
                time.sleep(max(0.1, options["interval"]))
        except KeyboardInterrupt:
            self.stdout.write("Worker stopped.")
