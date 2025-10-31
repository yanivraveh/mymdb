import json
import os
import uuid
from django.core.management.base import BaseCommand
from kafka import KafkaConsumer
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


class Command(BaseCommand):
    help = "Consume Kafka chat-messages and broadcast to local Channels groups"

    def handle(self, *args, **options):
        bootstrap = os.getenv("BOOTSTRAP_SERVERS", "localhost:29092")
        topic = os.getenv("TOPIC_NAME", "chat-messages")
        group_id = os.getenv("GROUP_ID") or f"django-broadcaster-{uuid.uuid4()}"

        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=bootstrap,
            auto_offset_reset="earliest",
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            group_id=group_id,
            enable_auto_commit=True,
        )

        self.stdout.write(self.style.SUCCESS(f"[broadcaster] {bootstrap} topic={topic} group={group_id}"))
        channel_layer = get_channel_layer()

        for msg in consumer:
            payload = msg.value or {}
            room = payload.get("room")
            username = payload.get("username") or "Anonymous"
            message = payload.get("message") or ""
            timestamp = payload.get("timestamp")

            if not room:
                continue

            group = f"chat_{room}"
            async_to_sync(channel_layer.group_send)(
                group,
                {
                    "type": "chat.message",
                    "username": username,
                    "message": message,
                    "timestamp": timestamp,
                },
            )




