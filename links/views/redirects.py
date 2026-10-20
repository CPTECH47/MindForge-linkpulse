import logging

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.db import DatabaseError
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from ..forms import PasswordForm
from ..models import Link
from ..services.policy import policy
from ..services.rate_limits import consume
from ..services.redirects import admit_redirect, evaluate_rules, new_grant
from ..services.tracking import client_ip, context_for_request, private_key

logger = logging.getLogger(__name__)


def unavailable(request):
    response = render(
        request,
        "links/visitor.html",
        {
            "heading": "Please try again shortly",
            "reason": "LinkPulse could not complete this request. No redirect was issued.",
        },
        status=503,
    )
    response["Retry-After"] = "5"
    return response


@require_http_methods(["GET", "HEAD"])
def redirect_link(request, alias):
    try:
        if request.method == "HEAD":
            link = get_object_or_404(Link, alias=alias)
            decision = evaluate_rules(
                link,
                request.session.get(f"grant:{link.pk}"),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )
            response = HttpResponse(status=decision.status)
            if decision.destination:
                response["Location"] = decision.destination
            return response
        context = context_for_request(request)
        # Resolve the ID only to retrieve a grant; admission reloads authoritative state under lock.
        link_id = Link.objects.values_list("pk", flat=True).get(alias=alias)
        link, decision = admit_redirect(alias, context, request.session.get(f"grant:{link_id}"))
    except Link.DoesNotExist:
        raise Http404("Short link not found") from None
    except DatabaseError:
        logger.exception("Redirect transaction failed")
        return unavailable(request)
    if decision.destination:
        response = HttpResponseRedirect(decision.destination)
        # Avoid leaking the short link / password gate to the destination.
        response["Referrer-Policy"] = "no-referrer"
    else:
        response = render(
            request,
            "links/visitor.html",
            {
                "heading": "This link needs a password"
                if decision.outcome == "password"
                else "This link is unavailable",
                "reason": decision.message,
                "link": link,
                "form": PasswordForm() if decision.outcome == "password" else None,
            },
            status=decision.status,
        )
    response.set_cookie(
        "lp_visitor",
        context["cookie"],
        max_age=2592000,
        secure=not settings.DEBUG,
        httponly=True,
        samesite="Lax",
    )
    return response


@require_POST
def unlock_link(request, alias):
    try:
        link = get_object_or_404(Link, alias=alias)
        key = f"unlock:{link.pk}:" + private_key(client_ip(request))
        if not consume(key, policy().password_rate_limit):
            response = render(
                request,
                "links/visitor.html",
                {
                    "heading": "Too many attempts",
                    "reason": "Please wait a minute before trying this password again.",
                },
                status=429,
            )
            response["Retry-After"] = "60"
            return response
        form = PasswordForm(request.POST)
        if (
            form.is_valid()
            and link.password_hash
            and check_password(form.cleaned_data["password"], link.password_hash)
        ):
            request.session[f"grant:{link.pk}"] = new_grant(link)
            suffix = "?src=" + request.POST["source"] if request.POST.get("source") in {"qr", "bio"} else ""
            return redirect(reverse("redirect_link", args=[alias]) + suffix)
        form.add_error(None, "Incorrect password.")
        return render(
            request,
            "links/visitor.html",
            {
                "heading": "This link needs a password",
                "reason": "Enter the password shared by the link owner.",
                "link": link,
                "form": form,
            },
            status=403,
        )
    except DatabaseError:
        return unavailable(request)
