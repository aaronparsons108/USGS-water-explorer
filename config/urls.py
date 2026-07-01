from django.contrib import admin
from django.urls import path, include

from explorer import views as explorer_views

urlpatterns = [
    #path('admin/', admin.site.urls),
    path("explorer/", include("explorer.urls")),
    # Serve the explorer app at the site root too (200, so health checks pass).
    path("", explorer_views.index, name="home"),
]