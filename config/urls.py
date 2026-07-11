from django.contrib import admin
from django.urls import path, include

from datasets import views as datasets_views

urlpatterns = [
    #path('admin/', admin.site.urls),
    path("datasets/", include("datasets.urls")),
    path("explorer/", include("explorer.urls")),
    # Land on the datasets list (200, so health checks pass).
    path("", datasets_views.list_view, name="home"),
]