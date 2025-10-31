from django.apps import AppConfig
import os

class ChatConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'chat'

    def ready(self):
        # Make Kafka mandatory; start broadcaster inside ASGI process
        # Avoid starting in management commands that aren't serving ASGI, if you prefer:
        # if os.environ.get("RUN_MAIN") != "true": return
        from .kafka_background import start_kafka_broadcaster
        start_kafka_broadcaster()

