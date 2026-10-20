# Deployment, operations and verification

Use Python 3.12, PostgreSQL and `requirements.lock`, which records the tested dependency versions. `requirements.txt` documents intentional direct-dependency ranges. Refresh security patches and the lock before internet deployment.

## Production environment

| Variable | Required configuration |
| --- | --- |
| DEBUG | `false` |
| SECRET_KEY | Unique random value of at least 50 characters. Generate using `python -c "import secrets; print(secrets.token_urlsafe(64))"`. |
| DATABASE_URL | PostgreSQL URL; URL-encode credentials and configure provider-required TLS. |
| PUBLIC_BASE_URL | Canonical HTTPS origin, e.g. `https://links.yourdomain.com`. |
| ALLOWED_HOSTS | Explicit comma-separated hosts, no wildcard. |
| CSRF_TRUSTED_ORIGINS | Canonical HTTPS origin and any other trusted management origins. |
| TRUST_PROXY | True only when a trusted proxy removes client-supplied forwarding headers and sets X-Forwarded-Proto itself. |
| TRUST_PROXY_IP | True only when a trusted proxy overwrites X-Real-IP with the client address. |
| GEOIP_DATABASE | Optional override; defaults to `data/geoip-country.mmdb`. Install using `manage.py install_geoip`. |
| EVENT_RETENTION_DAYS | Default 30, used until an administrator saves platform settings. |

Production refuses the development secret, SQLite, wildcard/empty hosts and a non-HTTPS public URL. Secure cookies, HTTPS redirects, HSTS, MIME sniffing protection and frame restrictions are enabled. Application pages use a restrictive content security policy. Django admin retains its own script requirements.

Run once as a release job:

```sh
python manage.py check --deploy --fail-level WARNING
python manage.py migrate --noinput
python manage.py collectstatic --noinput
```

Web and worker commands:

```sh
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --threads 2 --timeout 30
python manage.py process_clicks --loop --batch-size 100 --interval 2
```

Configure HTTPS at the ingress. Compose is a local HTTP demonstration with loopback binding; adapt proxy routing and the health check for production. Multi-replica deployments should run migrations in a single release job rather than each web process.

`/health/` checks database connectivity without returning credentials/details. Monitor worker progress separately: pending-event count, oldest pending age and exhausted retries. The staff platform screen shows pending and exhausted counts.

## Country lookup and platform policy

Run `python manage.py install_geoip` during initial setup and monthly afterwards. It downloads DB-IP Lite country data over HTTPS, bounds file sizes, validates the MMDB with a real lookup and atomically installs it. `--month YYYY-MM` selects a release if the current month's data is not yet available. `--file /path/to/country.mmdb` installs a locally supplied compatible database without network access. The database is ignored by Git and Docker build context.

Compose shares the `geoip_data` volume between web and worker. Run `docker compose exec web python manage.py install_geoip` once after startup; both processes can then use it. Other hosts must install the file during release or mount it persistently at `GEOIP_DATABASE`. Database updates are recognized without a restart. Country lookup uses the source address only when it is globally routable. Proxy IP trust must only be enabled when a trusted proxy overwrites X-Real-IP.

The app includes DB-IP attribution in its footer, as required by the [CC BY 4.0 country dataset](https://db-ip.com/db/download/ip-to-country-lite). No lookup API key is required. Raw IPs are not stored in analytics; separately configure web-server log retention.

Authorized administrators can save one Platform settings record in `/admin/` to change signup availability, creation/password rate limits and event retention. Saved policy takes effect without a restart and supersedes corresponding environment defaults. Database credentials, proxy trust and secrets remain environment-only.

## Maintenance and recovery

Schedule `python manage.py cleanup_data` daily using the hosting platform's scheduler. It deletes events older than retention, imports older than one day and old rate buckets. Lifetime counters remain. Historical reports cannot include deleted events. Scheduling is an operator step, not enabled automatically.

After repairing enrichment failures:

```sh
python manage.py retry_clicks
python manage.py process_clicks
```

Never reset link counters to repair enrichment. Worker restarts enrich in place without recounting. Configure PostgreSQL backups and test restoration to a separate database; restore counters and events together. Keep secrets in a secret manager. Secret-key rotation invalidates sessions, grants and browser identifiers and should be planned accordingly.

An administrator can reset a local account with `python manage.py changepassword USERNAME`. Password-reset email delivery is not configured.

## Tests

Run `python manage.py test --noinput`. PostgreSQL runs the complete suite; SQLite skips the three concurrency tests. Tests require a database user able to create and drop a disposable `test_` database. CI provisions a separate PostgreSQL service.

Coverage includes URL/alias validation, generated-code collision retries, password hashing, owner isolation across screens/JSON/QR/CSV, rule order, click caps, password grants, device routing, dynamic blocklist, HEAD behavior, transaction rollback, retryable DB failure, analytics periods/bots/browser estimates, worker idempotency/retry recovery, real PNG output, CSV size/encoding/duplicates/revalidation/repeat confirmation, export formula neutralization, CSRF, escaping, account flows, retention and admin audits.

PostgreSQL concurrency tests check eight simultaneous requests for one available click, an atomic shared rate limit and multiple enrichment workers claiming the same queue without double processing.

CI also detects missing migrations, collects static assets and runs production deployment checks. No latency or throughput target has been benchmarked.

## Operating limits

- Raw event capture waits for database commit; enrichment runs asynchronously.
- General request/traffic flood protection belongs at the trusted ingress. App fixed-window rate limits are basic controls, not DDoS mitigation.
- Browser, device, bot and country classification are estimates; neither people counts nor verified location.
- URL structure checks and manual domain blocks cannot prove a public destination is safe.
- Shared workspace invitations, per-user domains, public API and email infrastructure need additional implementation.
