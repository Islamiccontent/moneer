from importlib import import_module

from django.apps import AppConfig


class TranslateConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "translate"
    verbose_name = "الترجمة"

    def ready(self):
        import_module(f"{self.name}.signals")
