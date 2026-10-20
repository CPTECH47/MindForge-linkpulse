import secrets
import string

from django.contrib.auth.hashers import make_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from links.models import AuditLog, Link
from links.services.policy import policy
from links.services.rate_limits import consume
from links.validators import RESERVED, validate_alias, validate_destination


class RateLimited(ValidationError):
    pass


def save_link(actor, workspace, data, instance=None, administrator=False):
    if administrator:
        permission = "links.change_link" if instance else "links.add_link"
        if not actor.is_staff or not actor.has_perm(permission):
            raise PermissionDenied
    elif workspace.owner_id != actor.pk:
        raise PermissionDenied
    if instance is None and not consume(f"create:{actor.pk}", policy().creation_rate_limit):
        raise RateLimited("Creation limit reached. Please wait a minute and retry.")
    data = dict(data)
    tags = list(data.pop("tags", []))
    password = data.pop("password", "")
    clear_password = data.pop("clear_password", False)
    for field in ["destination", "mobile_url", "desktop_url"]:
        if data.get(field):
            data[field] = validate_destination(data[field])
    for field in ["campaign", "folder"]:
        if data.get(field):
            group = data[field]
            if group.workspace_id != workspace.pk:
                raise ValidationError("Organization belongs to another workspace.")
            if group.archived and (not instance or getattr(instance, field + "_id") != group.pk):
                raise ValidationError("Archived groups cannot be assigned to new links.")
    if any(tag.workspace_id != workspace.pk for tag in tags):
        raise ValidationError("Tags belong to another workspace.")
    existing_tags = set(instance.tags.values_list("pk", flat=True)) if instance else set()
    if any(tag.archived and tag.pk not in existing_tags for tag in tags):
        raise ValidationError("Archived tags cannot be assigned to new links.")
    alias = data.get("alias", "").strip()
    if alias:
        validate_alias(alias)
    for _ in range(8):
        try:
            with transaction.atomic():
                if instance:
                    link = Link.objects.select_for_update().get(pk=instance.pk, workspace=workspace)
                    if data.get("alias", link.alias) != link.alias:
                        raise ValidationError("The published alias cannot be changed.")
                    if link.status == Link.Status.BLOCKED and not administrator:
                        raise ValidationError("Only an administrator can restore a blocked link.")
                    if link.events.exists() and data.get("campaign") != link.campaign:
                        raise ValidationError("Campaign cannot change after visits have been recorded.")
                    link.rules_version += 1
                else:
                    link = Link(workspace=workspace)
                    data["alias"] = alias or "".join(
                        secrets.choice(string.ascii_letters + string.digits) for _ in range(7)
                    )
                    if data["alias"].lower() in RESERVED:
                        continue
                for field in [
                    "title",
                    "alias",
                    "destination",
                    "mobile_url",
                    "desktop_url",
                    "campaign",
                    "folder",
                    "expires_at",
                    "max_clicks",
                    "status",
                ]:
                    if field in data:
                        setattr(link, field, data[field])
                if link.status == Link.Status.BLOCKED and not administrator:
                    raise ValidationError("Administrator status cannot be set by users.")
                if password:
                    link.password_hash = make_password(password)
                elif clear_password:
                    link.password_hash = ""
                # Alias uniqueness is arbitrated by the DB so generated-code races can retry.
                link.full_clean(exclude=["tags"], validate_unique=False)
                link.save()
                link.tags.set(tags)
                AuditLog.objects.create(
                    actor=actor,
                    link=link,
                    action=("admin." if administrator else "")
                    + ("link.edited" if instance else "link.created"),
                )
                return link
        except IntegrityError:
            if alias or instance:
                raise ValidationError("That alias is already taken. Choose another.") from None
    raise ValidationError("Could not allocate an alias. Please retry.")
