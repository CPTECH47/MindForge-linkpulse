from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("analytics/data/", views.analytics_data, name="analytics_data"),
    path("links/", views.link_list, name="link_list"),
    path("links/new/", views.link_edit, name="link_create"),
    path("links/preview/", views.link_preview, name="link_preview"),
    path("links/export/", views.export_links, name="export_links"),
    path("links/<int:pk>/", views.link_detail, name="link_detail"),
    path("links/<int:pk>/edit/", views.link_edit, name="link_edit"),
    path("links/<int:pk>/toggle/", views.link_toggle, name="link_toggle"),
    path("links/<int:pk>/qr.png", views.link_qr, name="link_qr"),
    path("r/<str:alias>/", views.redirect_link, name="redirect_link"),
    path("r/<str:alias>/unlock/", views.unlock_link, name="unlock_link"),
    path("organize/", views.organize, name="organize"),
    path("organize/<str:kind>/<int:pk>/", views.group_edit, name="group_edit"),
    path("organize/<str:kind>/<int:pk>/delete/", views.group_delete, name="group_delete"),
    path("settings/", views.settings_view, name="settings"),
    path("workspaces/switch/", views.switch_workspace, name="switch_workspace"),
    path("workspaces/create/", views.create_workspace, name="create_workspace"),
    path("b/<slug:slug>/", views.bio_page, name="bio_page"),
    path("imports/", views.import_csv, name="import_csv"),
    path("imports/sample.csv", views.sample_csv, name="sample_csv"),
    path("imports/<uuid:pk>/", views.import_batch, name="import_batch"),
    path("platform/", views.platform_analytics, name="platform_analytics"),
    path("health/", views.health, name="health"),
]
