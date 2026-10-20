from django import forms

from ..models import BioPage, Link


class BioForm(forms.ModelForm):
    class Meta:
        model = BioPage
        fields = ["slug", "title", "description", "published", "links"]
        widgets = {"links": forms.CheckboxSelectMultiple}

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["links"].queryset = Link.objects.filter(workspace=workspace)


class CSVForm(forms.Form):
    file = forms.FileField(
        label="CSV file", help_text="UTF-8 CSV, up to 200 rows and 256 KB. Download the sample below."
    )
