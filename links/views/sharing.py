import csv
import io

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from ..context_processors import current_workspace
from ..forms import BioForm, CSVForm
from ..models import BioPage, ImportBatch, Link
from ..services.imports import HEADERS, confirm_batch, preview_rows, read_csv
from ..services.policy import policy
from ..services.rate_limits import consume
from ..services.tracking import geolocation_status
from .common import form_error


@login_required
@require_GET
def link_qr(request, pk):
    link = get_object_or_404(Link, pk=pk, workspace=current_workspace(request))
    image = qrcode.make(link.short_url + "?src=qr")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    response = HttpResponse(buffer.getvalue(), content_type="image/png")
    if request.GET.get("download"):
        response["Content-Disposition"] = f'attachment; filename="{link.alias}-qr.png"'
    return response


@login_required
@require_http_methods(["GET", "POST"])
def settings_view(request):
    workspace = current_workspace(request)
    bio = BioPage.objects.filter(workspace=workspace).first()
    form = BioForm(request.POST or None, instance=bio, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        page = form.save(commit=False)
        page.workspace = workspace
        try:
            with transaction.atomic():
                page.save()
                form.save_m2m()
        except IntegrityError:
            form.add_error("slug", "That public address is already in use.")
        else:
            messages.success(request, "Bio page saved.")
            return redirect("settings")
    return render(
        request,
        "links/settings.html",
        {
            "form": form,
            "bio": bio,
            "public_base_url": settings.PUBLIC_BASE_URL,
            "retention": policy().event_retention_days,
            "geolocation": geolocation_status(),
        },
    )


@require_GET
def bio_page(request, slug):
    bio = get_object_or_404(BioPage, slug=slug, published=True)
    # Defense in depth: even a manually edited M2M cannot expose another workspace's links.
    links = (
        bio.links.filter(workspace=bio.workspace, status=Link.Status.ACTIVE)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .order_by("title")
    )
    return render(request, "links/bio.html", {"bio": bio, "bio_links": links})


@login_required
@require_http_methods(["GET", "POST"])
def import_csv(request):
    form = CSVForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            if not consume(f"import:{request.user.pk}", 10):
                raise ValidationError("Too many previews. Try again in a minute.")
            rows = read_csv(form.cleaned_data["file"])
            workspace = current_workspace(request)
            results = preview_rows(workspace, rows)
            batch = ImportBatch.objects.create(workspace=workspace, rows=rows, results=results)
        except ValidationError as error:
            form_error(form, error)
        else:
            return redirect("import_batch", pk=batch.pk)
    return render(request, "links/import.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
def import_batch(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk, workspace=current_workspace(request))
    if request.method == "POST":
        try:
            batch = confirm_batch(request.user, pk)
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
        else:
            messages.success(request, "Import completed. Each row's result is shown below.")
        return redirect("import_batch", pk=pk)
    return render(
        request,
        "links/import_batch.html",
        {"batch": batch, "ready": sum(not r["errors"] for r in batch.results)},
    )


def safe_cell(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


@login_required
@require_GET
def export_links(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="linkpulse-links.csv"'
    writer = csv.writer(response)
    writer.writerow(["title", "alias", "destination", "status", "lifetime_redirects", "created_at"])
    for link in Link.objects.filter(workspace=current_workspace(request)).iterator():
        writer.writerow(
            [
                safe_cell(value)
                for value in [
                    link.title,
                    link.alias,
                    link.destination,
                    link.status,
                    link.successful_redirects,
                    link.created_at.isoformat(),
                ]
            ]
        )
    return response


@login_required
@require_GET
def sample_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="linkpulse-import-sample.csv"'
    writer = csv.writer(response)
    writer.writerow(HEADERS)
    writer.writerow(["Python documentation", "https://docs.python.org/3/", "", "", "", "100", ""])
    return response


@require_GET
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
