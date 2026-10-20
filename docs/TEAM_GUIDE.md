# Five-developer guide

## Tejas Pant: interface

Own page layouts, shared CSS, navigation and the creation wizard in `static/js/app.js`. Explain responsive navigation, the two-step form and validation errors. JavaScript enhances the experience; Django validates every published value. Jaanvi owns the dashboard templates and `static/js/analytics.js`; Mansi owns sharing/import templates. User content uses template escaping or DOM `textContent`.

Demonstrate a custom alias, rule review and the resulting detail page.

## Charchit Pant: models and accounts

Own models, migrations, forms, workspace context, shared link service and management/account views. Explain foreign keys, ownership, unique aliases and collision retry. Manual creation and imports use the same service. Aliases and visited campaigns remain fixed to preserve history.

Demonstrate workspace switching, group rename/archive/safe deletion, tag reports and rejected cross-owner access. Explain why an availability check alone cannot prevent concurrent duplicate aliases.

## Pulkit Joshi: redirect rules and security

Own redirect service, validators, rate limits, visitor views and moderation actions. Explain the transaction, row lock, rule order and version-bound 15-minute password grants. Takedowns and domain blocks are rechecked at redirect time.

Demonstrate a two-click link, the third rejection, password gate and pause. Bots count toward the cap; HEAD does not. Show the PostgreSQL final-click concurrency test.

## Jaanvi Kandpal: capture and analytics

Own tracking, worker, reporting, retry and retention commands. Explain the raw event as a durable queue: commit first, enrich later, never recount. Show exponential retries and PostgreSQL `SKIP LOCKED`. Define period redirects, likely humans, browser estimates, identification coverage and unknown countries honestly.

Stop the worker, visit a new link, show the raw count and pending event, then process it and show classification. Distinguish explicitly labeled synthetic seed data from real new visits.

## Mansi Nagarkoti: integration and deployment

Own imports, QR/bio flows, Docker/CI, demo seeding, documentation and integration tests. Explain that QR uses the same short link plus a source hint. CSV preview publishes nothing; confirmation revalidates and locks the batch, so repeats do not duplicate links.

Demonstrate one valid CSV row, one invalid scheme and a duplicate alias; confirm ready rows, inspect results, download PNG and open the public bio page. Show country-database readiness and the installer, plus administrator business-record editing and platform policy settings.

## Commit ownership

Follow [the contribution handoff](CONTRIBUTIONS.md) and the exact file assignment in `team-scopes.json`. Each branch contains only its member's assigned files and is pushed using that member's authenticated GitHub account. An authorized operator can also use the documented same-Mac token workflow.

## Five-minute demo

1. **0:00–0:45:** Introduce the workspace and central link record. Use a fresh workspace or clearly identify synthetic seeded data.
2. **0:45–1:45:** Create a campaign link with a two-click cap. Visit twice and show the third rejection.
3. **1:45–2:30:** Open a password link, then pause it. Explain why an old grant cannot bypass the pause.
4. **2:30–3:20:** Show live metrics, pending/classified counts and a QR download. Avoid claiming conversions.
5. **3:20–4:15:** Preview a valid/invalid CSV, confirm it and review durable results. Open the bio page.
6. **4:15–5:00:** Show administrator takedown/domain block, the concurrency-test result and deployment architecture.

## Jury questions

**Two visitors take the last click?** PostgreSQL locks the link row. Exactly one admission succeeds; the test checks eight simultaneous requests.

**Worker crashes?** Raw events and counters are already committed. Restarting enriches pending events without counting again.

**Does validation prove a URL is safe?** No. It rejects invalid/obvious prohibited destinations and applies the current blocklist; it is not malware scanning.

**Why no Celery or Redis?** The event table plus management-command worker provides durable asynchronous enrichment with fewer systems for the team to maintain. Reassess after measuring volume.

**Are visitors exact?** No. They are browser-cookie estimates on likely-human visits, with identification coverage shown.

**Why PostgreSQL when SQLite works?** Concurrent row locks and worker claiming are PostgreSQL guarantees. SQLite is a single-user development convenience and is refused in production.
