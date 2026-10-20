from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from ..models import Workspace
from ..services.policy import policy
from ..services.rate_limits import consume
from ..services.tracking import client_ip, private_key


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST":
        if not consume("login:" + private_key(client_ip(request)), 20):
            form.add_error(None, "Too many login attempts. Try again in a minute.")
        elif form.is_valid():
            login(request, form.get_user())
            return redirect("dashboard")
    return render(request, "registration/login.html", {"form": form})


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = UserCreationForm(request.POST or None)
    if not policy().signup_enabled:
        return render(
            request,
            "links/visitor.html",
            {
                "heading": "Registration is paused",
                "reason": "The administrator has temporarily paused new accounts.",
            },
            status=403,
        )
    if request.method == "POST":
        if not consume("signup:" + private_key(client_ip(request)), 5):
            form.add_error(None, "Too many signups. Try again in a minute.")
        elif form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
                    Workspace.objects.create(owner=user, name="My workspace")
            except IntegrityError:
                form.add_error("username", "That username is already taken.")
            else:
                login(request, user)
                return redirect("dashboard")
    return render(request, "registration/signup.html", {"form": form})
