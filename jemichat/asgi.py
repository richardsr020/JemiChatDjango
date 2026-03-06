import os
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.sessions import SessionMiddlewareStack
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jemichat.settings')

django_asgi_application = get_asgi_application()

from .routing import websocket_urlpatterns

application = ProtocolTypeRouter(
    {
        'http': django_asgi_application,
        'websocket': SessionMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)
