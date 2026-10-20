# LinkPulse

A complete Django application for creating short links, enforcing redirect rules, and understanding their traffic. Built for the five-person project with Django 5.2 LTS, PostgreSQL, and ordinary HTML, CSS, and JavaScript.

**Team:** MindForge · **Repository:** `MindForge-linkpulse`

## Problem statement

Basic URL shorteners map a short code to a destination, but teams also need to control access, organize campaigns and measure results. LinkPulse addresses the complete link lifecycle: creating unique aliases, enforcing status/expiry/password/click-limit rules, reliably recording visits, and turning real link and campaign data into useful reports. Invalid URLs, duplicate aliases and abusive destinations must be handled without exposing another user's data or losing historical analytics.

## Solution

LinkPulse brings creation, sharing, redirect rules, organization and analytics into one workspace. A central link record connects campaigns, folders, tags, QR codes and visits. Django validates creation and checks current rules on every redirect. PostgreSQL commits each allowed redirect count together with its click event, and a background worker enriches saved visits for reporting. Owners manage their own workspaces; administrators can disable abusive links and maintain a domain blocklist.

## Live demo

**Public live link: pending deployment.** A hosted URL will be added here after deployment is verified. The local development address below is not a public submission link.

Local preview: [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Screenshots

The dashboard below contains explicitly labeled synthetic demonstration data. The detail screenshot shows a link created through the browser walkthrough.

### Dashboard

![LinkPulse dashboard with synthetic demo data](docs/screenshots/dashboard.png)

### Link details and sharing

![LinkPulse saved link details](docs/screenshots/link-details.png)

### Tag performance and group management

![LinkPulse tag performance and group editing](docs/screenshots/tag-performance.png)

## Tech stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.12 and Django 5.2 LTS |
| Database | PostgreSQL; SQLite for single-user local development only |
| Frontend | Django templates, HTML, CSS and vanilla JavaScript |
| Click enrichment | Django management-command worker, user-agents; optional local GeoIP database |
| QR generation | qrcode and Pillow |
| Runtime and deployment | Gunicorn, WhiteNoise, Docker and Docker Compose |
| Verification | Django test framework, PostgreSQL concurrency tests and GitHub Actions |

## Features

- Registration, sign-in, sign-out and isolated personal workspaces.
- Two-step link creation, generated or custom aliases, draft validation, search and editing.
- Real status, expiry, click-limit, password and mobile/desktop redirect rules.
- Campaign/folder/tag creation, renaming, archiving, safe deletion, group performance reports and public link-in-bio pages.
- Transactional click capture and exact PostgreSQL click caps under concurrent requests.
- Background enrichment, retries, bot heuristics, browser/device parsing and optional local country lookup.
- Live dashboard: periods, campaigns, daily activity, traffic breakdowns, browser estimates, alerts and per-link history.
- Downloadable QR codes, CSV preview/confirmation, row-level results and CSV export.
- Administrator editing of links, workspaces, groups and bio pages; blocklist, takedowns/restoration, audit records and platform reporting.
- Editable platform registration, creation/password rate limits and event-retention settings.
- Shared rate limits, CSRF protection, password hashes, ownership checks, security headers and retention commands.
- Automated integration/concurrency tests, Docker setup and GitHub Actions.

No frontend build, paid API keys or external URL-preview requests are required.

## Secrets and repository hygiene

Never commit `.env`, database credentials, API keys or local databases. `.gitignore` excludes environment files, virtual environments, caches, generated static files, logs and temporary artifacts. `.env.example` contains placeholders only and is the safe configuration template to copy locally. Supply production secrets through the hosting provider's environment settings.

## Run locally

Use **Python 3.12**. macOS's bundled Python 3.9 is too old.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python manage.py migrate
python manage.py install_geoip
python manage.py seed_demo
python manage.py runserver 127.0.0.1:8000
```

Open <http://127.0.0.1:8000>. The seed command prints a newly generated demo password and never resets an existing account. Choose **Demo · synthetic data** after signing in. These sample events are explicitly synthetic; newly registered accounts start empty.

In another terminal:

```sh
source .venv/bin/activate
python manage.py process_clicks --loop
```

Without the worker, raw clicks and lifetime counters still save; human/device/browser metrics remain pending. A one-off `python manage.py process_clicks` processes one batch.

Create an administrator with `python manage.py createsuperuser`, then use `/admin/`. Staff need relevant Django permissions; a superuser has all permissions. Admins can create/edit business records and disable links through explicit actions. Counters, raw click events and audits remain protected from manual changes. Platform settings control registration, rate limits and retention.

### PostgreSQL

SQLite is a single-user development convenience. PostgreSQL is required for concurrent traffic, multiple workers, full tests and every production deployment.

```sh
export DATABASE_URL='postgresql://linkpulse:your-password@127.0.0.1:5432/linkpulse'
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

Export the same environment in each terminal, including the worker. Direct Python commands do **not** auto-load `.env`.

### Docker Compose

```sh
cp .env.example .env
# Edit .env: set a generated SECRET_KEY and POSTGRES_PASSWORD.
docker compose up --build -d
docker compose exec web python manage.py install_geoip
docker compose exec web python manage.py seed_demo
docker compose exec web python manage.py createsuperuser
```

Compose runs PostgreSQL, web and worker processes and binds port 8000 to loopback. Use a URL-safe database password, or supply a fully URL-encoded `DATABASE_URL` pointing at the `db` service. The named volume preserves database state. `docker compose down` stops services without deleting that volume.

## Verify

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --noinput
python manage.py collectstatic --noinput
```

Concurrency tests run on PostgreSQL; SQLite skips them. The database user needs permission to create a disposable test database. See [operations](docs/OPERATIONS.md) for coverage and deployment checks.

## Correctness and metrics

Short links use `PUBLIC_BASE_URL/r/alias/`. Admission locks the link row, checks its current rules, increments the lifetime counter if allowed and saves the raw event in **one transaction**. HTTP 302 is issued after commit. Event-save failure rolls back the counter and returns HTTP 503. Background processing enriches saved events without counting again.

Every allowed redirect counts toward the cap, including bots. Password challenges, blocked attempts, owner previews and HEAD requests do not consume it. Counts describe redirects issued, not destination loads or conversions. Rule edits invalidate old password grants. Expired/disabled links retain history.

Reports use UTC calendar days. Human/device/browser/country breakdowns use classified allowed events. Browser estimates use distinct pseudonymous returning-browser cookie keys; first-time or cookie-blocked visits are unidentifiable, and coverage is shown. Bot classification is heuristic. QR/bio source parameters are hints that can be copied or spoofed.

Country lookup uses a local MMDB database. Run `python manage.py install_geoip` to download and validate the free DB-IP Lite data; no API key is needed. The default path is `data/geoip-country.mmdb`, overridable with `GEOIP_DATABASE`. The installer replaces the file atomically and preserves existing data on failure. Run it monthly for updates. No external lookup is made per visit, and raw IPs are not stored in analytics. Local/private addresses have no country; missing or broken data is reported in settings and the staff platform screen. IP Geolocation by [DB-IP](https://db-ip.com), under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The app includes attribution on its pages.

The administrator blocklist is **not a malware scanner**. Validation rejects unsafe schemes, credentials, private literal IP addresses, obvious internal hostnames and self-domain loops. The server never fetches destinations and cannot prove the safety or DNS history of arbitrary public domains.

## Guides

- [Architecture and contracts](docs/ARCHITECTURE.md)
- [Deployment, operations and tests](docs/OPERATIONS.md)
- [Five-developer ownership and demo script](docs/TEAM_GUIDE.md)
- [Environment example](.env.example)

No public deployment is created by this repository. Production needs hosting, PostgreSQL, an HTTPS domain, secrets, a running worker, backups and scheduled cleanup. Shared workspace invitations, per-user custom domains, public API, password-reset email delivery and external threat scanning are future enhancements.
