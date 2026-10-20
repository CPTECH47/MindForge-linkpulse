import hashlib
import hmac
import ipaddress
import logging
import re
import secrets
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.core import signing
from user_agents import parse

logger = logging.getLogger(__name__)
BOT_PATTERN = re.compile(
    r"bot|crawler|spider|slurp|preview|facebookexternalhit|headless|curl|wget|python-requests", re.I
)


def client_ip(request):
    # Do not trust user-provided X-Forwarded-For by default.
    value = request.META.get("REMOTE_ADDR", "")
    if settings.TRUST_PROXY_IP:
        value = request.META.get("HTTP_X_REAL_IP", value)
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return ""


def private_key(value):
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


@lru_cache(maxsize=1)
def geo_reader(path, modified=None):
    import geoip2.database

    return geoip2.database.Reader(path)


def country_for_ip(ip):
    if not settings.GEOIP_DATABASE or not ip:
        return ""
    try:
        if not ipaddress.ip_address(ip).is_global:
            return ""
        path = Path(settings.GEOIP_DATABASE)
        if not path.is_file():
            return ""
        return geo_reader(str(path), path.stat().st_mtime_ns).country(ip).country.iso_code or ""
    except Exception:
        # No raw IP or untrusted header values in logs.
        logger.warning("GeoIP lookup unavailable")
        return ""


def geolocation_status():
    path = Path(settings.GEOIP_DATABASE) if settings.GEOIP_DATABASE else None
    if path is None or not path.is_file():
        return {
            "ready": False,
            "message": "Country database not installed. Run python manage.py install_geoip.",
        }
    try:
        metadata = geo_reader(str(path), path.stat().st_mtime_ns).metadata()
        if "Country" not in metadata.database_type:
            raise ValueError("Not a country database")
        return {"ready": True, "message": "Local country lookup ready", "database": metadata.database_type}
    except Exception:
        return {
            "ready": False,
            "message": "Country database could not be opened. Reinstall it using install_geoip.",
        }


def context_for_request(request):
    token = None
    try:
        token = signing.loads(request.COOKIES.get("lp_visitor", ""), salt="visitor", max_age=2592000)
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
            token = None
    except signing.BadSignature:
        pass
    identified = token is not None
    token = token or secrets.token_hex(16)
    try:
        referrer = urlsplit(request.META.get("HTTP_REFERER", "")).hostname or ""
    except ValueError:
        referrer = ""
    return {
        "user_agent": request.META.get("HTTP_USER_AGENT", "")[:512],
        "referrer_host": referrer[:253],
        "visitor_key": private_key(token) if identified else "",
        "source": "qr"
        if request.GET.get("src") == "qr"
        else "bio"
        if request.GET.get("src") == "bio"
        else "link",
        "country": country_for_ip(client_ip(request)),
        "cookie": signing.dumps(token, salt="visitor"),
    }


def classify(user_agent):
    agent = parse(user_agent)
    device = (
        "tablet"
        if agent.is_tablet
        else "mobile"
        if agent.is_mobile
        else "desktop"
        if agent.is_pc
        else "other"
    )
    return {
        "browser": agent.browser.family[:80],
        "device": device,
        "is_bot": bool(agent.is_bot or BOT_PATTERN.search(user_agent) or not user_agent),
    }
