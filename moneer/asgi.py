"""ASGI config for the moneer project; exposes the ASGI callable as ``application``."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "moneer.settings")

application = get_asgi_application()
