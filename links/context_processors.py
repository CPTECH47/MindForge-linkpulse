from .models import Workspace


def current_workspace(request):
    if not request.user.is_authenticated:
        return None
    spaces = Workspace.objects.filter(owner=request.user)
    workspace = spaces.filter(pk=request.session.get("workspace_id")).first() or spaces.order_by("pk").first()
    if workspace is None:
        workspace = Workspace.objects.get_or_create(owner=request.user, name="My workspace")[0]
    return workspace


def workspace_context(request):
    if not request.user.is_authenticated:
        return {}
    return {"workspace": current_workspace(request), "workspaces": request.user.workspaces.all()}
