from django.contrib import admin

from ..forms import BioForm
from ..models import (
    BioPage,
    ImportBatch,
    Link,
)
from .analytics import ReadOnlyAdmin


class AdminBioForm(BioForm):
    class Meta(BioForm.Meta):
        fields = ["workspace", *BioForm.Meta.fields]

    def __init__(self, *args, **kwargs):
        instance = kwargs.get("instance")
        super().__init__(*args, workspace=instance.workspace if instance and instance.pk else None, **kwargs)
        self.fields["links"].queryset = Link.objects.all()

    def clean(self):
        data = super().clean()
        if any(
            link.workspace_id != getattr(data.get("workspace"), "pk", None) for link in data.get("links", [])
        ):
            self.add_error("links", "Every bio link must belong to the selected workspace.")
        return data


@admin.register(BioPage)
class BioAdmin(admin.ModelAdmin):
    form = AdminBioForm
    list_display = ["title", "workspace", "slug", "published"]
    list_filter = ["published"]


admin.site.register(ImportBatch, ReadOnlyAdmin)
