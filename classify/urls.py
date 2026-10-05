from django.urls import path

from . import views

app_name = "classify"
urlpatterns = [
    path("api/segment/", views.api_segment, name="api_segment"),
    path("api/segment/progress/", views.api_progress, name="api_progress"),
    path("classify/documents/<int:pk>.json", views.api, name="api"),
    path("classify/documents/<int:pk>/export.xlsx", views.export, name="export"),
]
