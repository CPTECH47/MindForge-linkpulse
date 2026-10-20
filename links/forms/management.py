from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from ..models import Campaign, Folder, Link, Tag
from ..validators import validate_alias, validate_destination


class LinkForm(forms.ModelForm):
    alias = forms.CharField(
        max_length=32,
        required=False,
        help_text="Optional. 4–32 letters, numbers, hyphens or underscores; case-sensitive.",
    )
    password = forms.CharField(
        required=False,
        min_length=8,
        max_length=128,
        widget=forms.PasswordInput,
        help_text="Optional. At least 8 characters. Leave blank to keep the current password.",
    )
    clear_password = forms.BooleanField(required=False, label="Remove the current password")
    expires_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        help_text="UTC. Leave blank for no expiry.",
    )

    class Meta:
        model = Link
        fields = [
            "title",
            "destination",
            "alias",
            "campaign",
            "folder",
            "tags",
            "expires_at",
            "max_clicks",
            "password",
            "clear_password",
            "mobile_url",
            "desktop_url",
            "status",
        ]
        widgets = {"tags": forms.CheckboxSelectMultiple}
        help_texts = {
            "max_clicks": "All successful redirects count, including bots. Blank means unlimited.",
            "mobile_url": "Optional destination for phones and tablets.",
            "desktop_url": "Optional destination for other devices.",
        }

    def __init__(self, *args, workspace, administrator=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        for field, model in [("campaign", Campaign), ("folder", Folder), ("tags", Tag)]:
            query = (
                model.objects.all()
                if administrator and workspace is None
                else model.objects.filter(workspace=workspace)
            )
            existing = []
            if self.instance.pk:
                existing = (
                    list(self.instance.tags.values_list("pk", flat=True))
                    if field == "tags"
                    else [getattr(self.instance, field + "_id")]
                )
            self.fields[field].queryset = query.filter(Q(archived=False) | Q(pk__in=existing))
        self.fields["status"].choices = (
            Link.Status.choices if administrator else [("active", "Active"), ("paused", "Paused")]
        )
        if self.instance.pk:
            self.fields["alias"].disabled = True
            if self.instance.events.exists():
                self.fields["campaign"].disabled = True

    def clean_alias(self):
        alias = self.cleaned_data["alias"].strip()
        if alias:
            validate_alias(alias)
            if Link.objects.filter(alias=alias).exclude(pk=self.instance.pk).exists():
                raise ValidationError("That alias is already taken.")
        return alias

    def clean_max_clicks(self):
        value = self.cleaned_data.get("max_clicks")
        if value is not None and value < 1:
            raise ValidationError("The click limit must be at least 1.")
        return value

    def clean(self):
        data = super().clean()
        for field in ["destination", "mobile_url", "desktop_url"]:
            if data.get(field):
                try:
                    data[field] = validate_destination(data[field])
                except ValidationError as error:
                    self.add_error(field, error)
        expiry = data.get("expires_at")
        if (
            expiry
            and expiry <= timezone.now()
            and (not self.instance.pk or expiry != self.instance.expires_at)
        ):
            self.add_error("expires_at", "Choose a future expiry time.")
        if data.get("password") and data.get("clear_password"):
            self.add_error("password", "Choose a new password or remove the password.")
        return data


class AdminLinkForm(LinkForm):
    class Meta(LinkForm.Meta):
        fields = ["workspace", *LinkForm.Meta.fields]

    def __init__(self, *args, **kwargs):
        instance = kwargs.get("instance")
        data = args[0] if args else kwargs.get("data")
        workspace = instance.workspace if instance and instance.pk else None
        if (
            workspace is None
            and data
            and str(data.get("workspace", "")).isascii()
            and str(data.get("workspace", "")).isdigit()
        ):
            from ..models import Workspace

            workspace = Workspace.objects.filter(pk=int(data["workspace"])).first()
        super().__init__(*args, workspace=workspace, administrator=True, **kwargs)
        if instance and instance.pk:
            self.fields["workspace"].disabled = True

    def clean(self):
        data = super().clean()
        workspace = data.get("workspace")
        for name in ["campaign", "folder"]:
            if data.get(name) and data[name].workspace_id != getattr(workspace, "pk", None):
                self.add_error(name, "Choose a group from the link's workspace.")
        if any(tag.workspace_id != getattr(workspace, "pk", None) for tag in data.get("tags", [])):
            self.add_error("tags", "Choose tags from the link's workspace.")
        return data


class GroupEditForm(forms.Form):
    name = forms.CharField(max_length=80)
    description = forms.CharField(max_length=240, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    archived = forms.BooleanField(required=False)

    def __init__(self, *args, campaign=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not campaign:
            self.fields.pop("description")


class OrganizationForm(forms.Form):
    kind = forms.ChoiceField(choices=[("campaign", "Campaign"), ("folder", "Folder"), ("tag", "Tag")])
    name = forms.CharField(max_length=80)
    description = forms.CharField(max_length=240, required=False, help_text="For campaigns.")
