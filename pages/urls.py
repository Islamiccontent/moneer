from django.urls import path

from . import views

app_name = "pages"

urlpatterns = [
    path("", views.home, name="home"),
    path("classify/", views.classify_page, name="classify"),
    path("classify/documents/<int:pk>/", views.classify_page, name="classify_document"),
    path("translate/", views.translate_page, name="translate"),
    path("translate/documents/", views.documents_page, name="documents"),
    path("translate/documents/<int:pk>/", views.translate_page, name="document"),
    path("translate/documents/<int:pk>/<slug:stage>/", views.translate_page, name="document_stage"),
    *[
        path(name, views.root_file, {"name": name}, name=f"root-{name}")
        for name in views.ROOT_FILES
        if name != views.HOME_FILE
    ],
]
