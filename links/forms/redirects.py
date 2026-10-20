from django import forms


class PasswordForm(forms.Form):
    password = forms.CharField(max_length=128, widget=forms.PasswordInput)
