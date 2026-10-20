"""Shared validation for web forms, imports, and redirect-time safety checks."""

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from .models import BlockedDomain

RESERVED = {
    "admin",
    "login",
    "logout",
    "signup",
    "links",
    "analytics",
    "static",
    "health",
    "accounts",
    "imports",
    "campaigns",
    "settings",
    "workspaces",
    "preview",
    "null",
    "undefined",
}


def validate_alias(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,32}", value) or value.lower() in RESERVED:
        raise ValidationError(
            "Use 4–32 letters, numbers, hyphens or underscores. This alias may be reserved."
        )
    return value


def blocked_host(host):
    host = host.lower().rstrip(".")
    # Exact hostname plus every parent, never suffix-match unrelated domains.
    labels = host.split(".")
    return BlockedDomain.objects.filter(
        enabled=True, hostname__in=[".".join(labels[i:]) for i in range(len(labels))]
    ).exists()


def validate_destination(value):
    value = value.strip()
    if not value or len(value) > 2048 or any(ord(c) < 33 or ord(c) == 127 for c in value) or "\\" in value:
        raise ValidationError("Enter a valid public HTTP or HTTPS URL without spaces or control characters.")
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        port = parts.port  # Trigger invalid-port validation.
    except (ValueError, UnicodeError):
        raise ValidationError("Invalid URL hostname or port.") from None
    if (
        parts.scheme.lower() not in {"http", "https"}
        or parts.username is not None
        or parts.password is not None
    ):
        raise ValidationError("Only HTTP and HTTPS URLs without embedded credentials are supported.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if re.fullmatch(r"[0-9.]+", host) or re.fullmatch(
            r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*", host
        ):
            raise ValidationError("Ambiguous numeric IP address formats are not allowed.") from None
        if "." not in host or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid")):
            raise ValidationError("Use a public internet hostname.") from None
    else:
        if not address.is_global:
            raise ValidationError("Private and reserved IP addresses are not allowed.")
    if host == urlsplit(settings.PUBLIC_BASE_URL).hostname:
        raise ValidationError("LinkPulse cannot shorten links to its own domain.")
    if blocked_host(host):
        raise ValidationError("This destination is blocked by the platform administrator.")
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority += f":{port}"
    result = urlunsplit((parts.scheme.lower(), authority, parts.path or "/", parts.query, parts.fragment))
    URLValidator(schemes=["http", "https"])(result)
    return result
