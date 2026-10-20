from django.core.exceptions import ValidationError
from django.db import transaction

from links.models import Campaign, Folder, Tag

GROUP_MODELS = {"campaign": Campaign, "folder": Folder, "tag": Tag}


@transaction.atomic
def update_group(group, name, description="", archived=False):
    model = type(group)
    group = model.objects.select_for_update().get(pk=group.pk)
    group.name = name.strip()
    group.archived = archived
    if isinstance(group, Campaign):
        group.description = description
    group.full_clean()
    group.save()
    return group


@transaction.atomic
def delete_group(group):
    group = type(group).objects.select_for_update().get(pk=group.pk)
    if group.links.exists():
        raise ValidationError(
            "This group is used by links. Archive it to preserve link organization and history."
        )
    group.delete()
