from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("api/audit/run/", views.api_audit_run, name="run"),
    path("api/audit/jobs/<int:pk>/", views.api_audit_job, name="job"),
    path("api/audit/jobs/<int:pk>/xlsx/", views.api_audit_xlsx, name="xlsx"),
    path("api/audit/translations/<int:pk>/", views.api_audit_latest, name="latest"),
]
