from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path

from links import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", views.login_view, name="login"),
    path("accounts/logout/", LogoutView.as_view(), name="logout"),
    path("accounts/signup/", views.signup, name="signup"),
    path("", include("links.urls")),
]
