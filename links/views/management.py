from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from ..context_processors import current_workspace
from ..forms import GroupEditForm, LinkForm, OrganizationForm
from ..models import AuditLog, Campaign, ClickEvent, Folder, Link, Tag, Workspace
from ..services.analytics import analytics
from ..services.links import save_link
from ..services.organization import GROUP_MODELS, delete_group, update_group
from .analytics import report_filters
from .common import form_error


@login_required
@require_GET
def link_list(request):
    workspace = current_workspace(request)
    links = (
        Link.objects.filter(workspace=workspace).select_related("campaign", "folder").prefetch_related("tags")
    )
    query = request.GET.get("q", "")[:120]
    if query:
        links = links.filter(
            Q(title__icontains=query) | Q(alias__icontains=query) | Q(destination__icontains=query)
        )
    for key in ["campaign", "folder", "tags"]:
        value = request.GET.get(key, "")
        if value.isdigit():
            links = links.filter(**{key: value})
    status = request.GET.get("status", "")
    if status in Link.Status.values:
        links = links.filter(status=status)
    return render(
        request,
        "links/list.html",
        {
            "page": Paginator(links, 15).get_page(request.GET.get("page")),
            "query": query,
            "campaigns": Campaign.objects.filter(workspace=workspace),
            "folders": Folder.objects.filter(workspace=workspace),
            "tags": Tag.objects.filter(workspace=workspace),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def link_edit(request, pk=None):
    workspace = current_workspace(request)
    instance = get_object_or_404(Link, pk=pk, workspace=workspace) if pk else None
    form = LinkForm(request.POST or None, workspace=workspace, instance=instance)
    if request.method == "POST" and form.is_valid():
        try:
            link = save_link(request.user, workspace, form.cleaned_data, instance)
        except ValidationError as error:
            form_error(form, error)
        else:
            messages.success(request, "Link updated." if pk else "Your link is ready to share.")
            return redirect("link_detail", pk=link.pk)
    return render(request, "links/form.html", {"form": form, "editing": bool(pk), "link": instance})


@login_required
@require_POST
def link_preview(request):
    form = LinkForm(request.POST, workspace=current_workspace(request))
    if not form.is_valid():
        return JsonResponse({"valid": False, "errors": form.errors.get_json_data()}, status=400)
    return JsonResponse(
        {
            "valid": True,
            "message": "Destination and rules are valid. Publishing will recheck alias availability.",
            "warnings": ["Password will be required."] if form.cleaned_data.get("password") else [],
        }
    )


@login_required
@require_GET
def link_detail(request, pk):
    link = get_object_or_404(Link, pk=pk, workspace=current_workspace(request))
    data = analytics(link.workspace, 30, link_id=link.pk)
    return render(
        request, "links/detail.html", {"link": link, "report": data, "events": link.events.all()[:20]}
    )


@login_required
@require_POST
def link_toggle(request, pk):
    with transaction.atomic():
        link = get_object_or_404(
            Link.objects.select_for_update(), pk=pk, workspace=current_workspace(request)
        )
        if link.status == Link.Status.BLOCKED:
            messages.error(request, "Only an administrator can restore this link.")
        else:
            link.status = Link.Status.PAUSED if link.status == Link.Status.ACTIVE else Link.Status.ACTIVE
            link.rules_version += 1
            link.save(update_fields=["status", "rules_version", "updated_at"])
            AuditLog.objects.create(actor=request.user, link=link, action=f"link.{link.status}")
            messages.success(request, f"Link {link.get_status_display().lower()}.")
    return redirect("link_detail", pk=pk)


@login_required
@require_http_methods(["GET", "POST"])
def organize(request):
    workspace = current_workspace(request)
    form = OrganizationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        model = {"campaign": Campaign, "folder": Folder, "tag": Tag}[form.cleaned_data["kind"]]
        defaults = {"description": form.cleaned_data["description"]} if model is Campaign else {}
        _, created = model.objects.get_or_create(
            workspace=workspace, name=form.cleaned_data["name"], defaults=defaults
        )
        messages.success(request, "Created." if created else "This name already exists.")
        return redirect("organize")
    return render(
        request,
        "links/organize.html",
        {
            "form": form,
            "groups": [
                {
                    "kind": kind,
                    "label": model.__name__,
                    "items": model.objects.filter(workspace=workspace)
                    .filter(**({} if request.GET.get("archived") == "1" else {"archived": False}))
                    .annotate(
                        link_count=Count("links", distinct=True), clicks=Sum("links__successful_redirects")
                    ),
                }
                for kind, model in GROUP_MODELS.items()
            ],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def group_edit(request, kind, pk):
    model = GROUP_MODELS.get(kind)
    if model is None:
        raise Http404
    group = get_object_or_404(model, pk=pk, workspace=current_workspace(request))
    form = GroupEditForm(
        request.POST if request.method == "POST" else None,
        campaign=kind == "campaign",
        initial={
            "name": group.name,
            "description": getattr(group, "description", ""),
            "archived": group.archived,
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            update_group(group, **form.cleaned_data)
        except (ValidationError, IntegrityError) as error:
            if isinstance(error, ValidationError):
                form_error(form, error)
            else:
                form.add_error("name", "That name is already in use in this workspace.")
        else:
            messages.success(request, "Group updated. Existing links and visits are preserved.")
            return redirect("organize")
    days, _, _ = report_filters(request)
    group_links = group.links.all()
    events = ClickEvent.objects.filter(
        link__in=group_links,
        outcome="allowed",
        occurred_at__gte=timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        - timedelta(days=days - 1),
    )
    return render(
        request,
        "links/group.html",
        {
            "form": form,
            "group": group,
            "kind": kind,
            "days": days,
            "link_count": group_links.count(),
            "clicks": group_links.aggregate(total=Sum("successful_redirects"))["total"] or 0,
            "period_clicks": events.count(),
            "top_links": group_links.annotate(
                period_clicks=Count("events", filter=Q(events__in=events))
            ).order_by("-period_clicks", "title")[:10],
        },
    )


@login_required
@require_POST
def group_delete(request, kind, pk):
    model = GROUP_MODELS.get(kind)
    if model is None:
        raise Http404
    group = get_object_or_404(model, pk=pk, workspace=current_workspace(request))
    try:
        delete_group(group)
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
        return redirect("group_edit", kind=kind, pk=pk)
    messages.success(request, "Unused group deleted.")
    return redirect("organize")


@login_required
@require_POST
def switch_workspace(request):
    try:
        workspace_id = int(request.POST.get("workspace", ""))
        if not 0 < workspace_id < 2**63:
            raise ValueError
    except (TypeError, ValueError):
        raise Http404("Workspace not found") from None
    workspace = get_object_or_404(Workspace, pk=workspace_id, owner=request.user)
    request.session["workspace_id"] = workspace.pk
    return redirect("dashboard")


@login_required
@require_POST
def create_workspace(request):
    name = request.POST.get("name", "").strip()[:80]
    if name and request.user.workspaces.count() < 10:
        workspace, _ = Workspace.objects.get_or_create(owner=request.user, name=name)
        request.session["workspace_id"] = workspace.pk
        messages.success(request, "Workspace ready.")
    else:
        messages.error(request, "Enter a name. Each account may have up to 10 workspaces.")
    return redirect("settings")
