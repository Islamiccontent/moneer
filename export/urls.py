from django.urls import path

from . import views

app_name = "export"

urlpatterns = [
    path("<int:pk>/<str:kind>/", views.download, name="download"),
]
