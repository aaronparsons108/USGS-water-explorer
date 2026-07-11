from django.urls import path

from . import views

app_name = "datasets"

urlpatterns = [
    path("", views.list_view, name="list"),
    path("new/", views.create_view, name="create"),
    path("pmcode-search/", views.pmcode_search, name="pmcode_search"),
    path("<int:pk>/setup/", views.setup_view, name="setup"),
    path("<int:pk>/setup/save/", views.setup_save, name="setup_save"),
    path("<int:pk>/sites/", views.sites_view, name="sites"),
    path("<int:pk>/sites/data/", views.sites_data, name="sites_data"),
    path("<int:pk>/sites/save/", views.sites_save, name="sites_save"),
    path("<int:pk>/discover/", views.discover_start, name="discover"),
    path("<int:pk>/download/", views.download_view, name="download"),
    path("<int:pk>/download/start/", views.download_start, name="download_start"),
    path("<int:pk>/job/", views.job_status, name="job_status"),
    path("<int:pk>/delete/", views.delete_view, name="delete"),
]
