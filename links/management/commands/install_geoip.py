"""Install DB-IP Lite's CC BY 4.0 country data, or validate a local compatible MMDB."""

import gzip
import os
import re
import shutil
import tempfile
import urllib.request
from pathlib import Path

import geoip2.database
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Install free DB-IP Lite country data. Requires attribution: https://db-ip.com (included in app)."

    def add_arguments(self, parser):
        parser.add_argument("--month", default=None, help="Release YYYY-MM; defaults to the current month.")
        parser.add_argument("--file", help="Install a local Country MMDB instead of downloading.")

    def handle(self, *args, **options):
        month = options["month"] or timezone.now().strftime("%Y-%m")
        if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", month):
            raise CommandError("Use a release month in YYYY-MM format.")
        destination = Path(settings.GEOIP_DATABASE)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".mmdb", delete=False) as output:
                temporary = Path(output.name)
                if options["file"]:
                    source = Path(options["file"])
                    if source.stat().st_size > 80 * 1024 * 1024:
                        raise CommandError("Country database exceeds 80 MB.")
                    with source.open("rb") as stream:
                        shutil.copyfileobj(stream, output)
                else:
                    url = f"https://download.db-ip.com/free/dbip-country-lite-{month}.mmdb.gz"
                    request = urllib.request.Request(
                        url, headers={"User-Agent": "LinkPulse-country-installer/1.0"}
                    )
                    with (
                        urllib.request.urlopen(request, timeout=30) as response,
                        tempfile.TemporaryFile() as compressed,
                    ):
                        total = 0
                        while chunk := response.read(65536):
                            total += len(chunk)
                            if total > 25 * 1024 * 1024:
                                raise CommandError("Download exceeds the 25 MB safety limit.")
                            compressed.write(chunk)
                        compressed.seek(0)
                        total = 0
                        with gzip.GzipFile(fileobj=compressed) as stream:
                            while chunk := stream.read(65536):
                                total += len(chunk)
                                if total > 80 * 1024 * 1024:
                                    raise CommandError("Uncompressed database exceeds 80 MB.")
                                output.write(chunk)
            with geoip2.database.Reader(str(temporary)) as reader:
                if "Country" not in reader.metadata().database_type:
                    raise CommandError("Expected a country MMDB database.")
                if not reader.country("8.8.8.8").country.iso_code:
                    raise CommandError("Country database failed its lookup check.")
            os.chmod(temporary, 0o644)
            os.replace(temporary, destination)
        except CommandError:
            raise
        except Exception as error:
            raise CommandError(
                f"Could not install country data ({type(error).__name__}). Check connectivity, release month and file permissions. Existing data was preserved."
            ) from error
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
        self.stdout.write(
            self.style.SUCCESS(
                "Country database installed and lookup verified. Attribution: IP Geolocation by DB-IP - https://db-ip.com (CC BY 4.0)."
            )
        )
