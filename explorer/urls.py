from django.urls import path

from . import views

app_name = "explorer"

urlpatterns = [
    path("", views.index, name="index_default"),
    path("<slug:slug>/", views.index, name="index"),
    path("<slug:slug>/results/", views.results, name="results"),
    path("<slug:slug>/download/<str:kind>.png", views.download_png, name="download_png"),
    path("<slug:slug>/download/sites.csv", views.download_csv, name="download_csv"),
]
