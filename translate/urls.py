from django.urls import path

from . import views

app_name = "translate"

urlpatterns = [
    path("api/translate/", views.api_translate, name="api_translate"),
    path("api/translate/run/", views.api_translate_run, name="api_translate_run"),
    path("api/translate/progress/", views.api_translate_progress, name="api_progress"),
    path("api/translate/languages/", views.api_languages, name="api_languages"),
    path("api/translate/documents/", views.api_documents, name="api_documents"),
    path("api/translate/documents/<int:pk>/", views.api_document, name="api_document"),
]
