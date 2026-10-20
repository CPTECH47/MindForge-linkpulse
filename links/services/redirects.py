"""Admission commits a redirect counter and its raw event in ONE transaction."""

from dataclasses import dataclass
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from links.models import ClickEvent, Link
from links.services.tracking import classify
from links.validators import validate_destination


@dataclass(frozen=True)
class Decision:
    outcome: str
    message: str
    status: int
    destination: str = ""


def grant_valid(link, grant):
    return (
        isinstance(grant, dict)
        and grant.get("version") == link.rules_version
        and isinstance(grant.get("until"), (int, float))
        and grant["until"] > timezone.now().timestamp()
    )


def evaluate_rules(link, grant=None, now=None, user_agent=""):
    now = now or timezone.now()
    if link.status != Link.Status.ACTIVE:
        return Decision("disabled", "This link has been paused or disabled.", 410)
    if link.expires_at and now >= link.expires_at:
        return Decision("expired", "This link has expired.", 410)
    if link.max_clicks is not None and link.successful_redirects >= link.max_clicks:
        return Decision("limit", "This link has reached its click limit.", 410)
    device = classify(user_agent)["device"]
    destination = (
        link.mobile_url if device in {"mobile", "tablet"} else link.desktop_url
    ) or link.destination
    try:
        validate_destination(destination)
    except ValidationError:
        return Decision("unsafe", "This destination is unavailable under the platform safety policy.", 410)
    if link.password_hash and not grant_valid(link, grant):
        return Decision("password", "Enter the link password to continue.", 403)
    return Decision("allowed", "Ready to redirect.", 302, destination)


def admit_redirect(alias, context, grant=None):
    with transaction.atomic():
        link = Link.objects.select_for_update().get(alias=alias)
        decision = evaluate_rules(link, grant, user_agent=context.get("user_agent", ""))
        if decision.outcome == "allowed":
            # Conditional update also protects the cap against unsupported row locks in SQLite.
            admitted = (
                Link.objects.filter(pk=link.pk)
                .filter(Q(max_clicks__isnull=True) | Q(successful_redirects__lt=F("max_clicks")))
                .update(successful_redirects=F("successful_redirects") + 1)
            )
            if not admitted:
                decision = Decision("limit", "This link has reached its click limit.", 410)
        ClickEvent.objects.create(
            link=link, outcome=decision.outcome, **{k: v for k, v in context.items() if k != "cookie"}
        )
    return link, decision


def new_grant(link):
    return {"version": link.rules_version, "until": (timezone.now() + timedelta(minutes=15)).timestamp()}
