"""WSGI config for the moneer project; exposes the WSGI callable as ``application``."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "moneer.settings")

application = get_wsgi_application()
