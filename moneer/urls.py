"""مسارات المشروع: الصفحة الرئيسية على / ولوحة الإدارة على /admin/ وتطبيقا classify وtranslate."""

from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "إدارة مُنير"
admin.site.site_title = "مُنير"
admin.site.index_title = "لوحة الإدارة"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("classify.urls")),
    path("", include("translate.urls")),
    path("", include("pages.urls")),
]
