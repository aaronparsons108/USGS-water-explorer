from django.urls import path

from . import views

app_name = "explorer"

urlpatterns = [
    path("", views.index, name="index"),
    path("results/", views.results, name="results"),
    path("download/<str:kind>.png", views.download_png, name="download_png"),
    path("download/sites.csv", views.download_csv, name="download_csv"),
]
