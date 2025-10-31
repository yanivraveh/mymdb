import json
import os
import uuid
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone
from kafka import KafkaProducer


def get_kafka_producer():
    bootstrap = os.getenv("BOOTSTRAP_SERVERS", "localhost:29092")
    # Lazy-init single producer per process
    if not hasattr(get_kafka_producer, "_producer"):
        get_kafka_producer._producer = KafkaProducer(
            bootstrap_servers=bootstrap,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8"),
            linger_ms=20,
            acks="all",
        )
    return get_kafka_producer._producer


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not getattr(user, "is_authenticated", False):
            # Close with app-defined code (4xxx range is allowed)
            await self.close(code=4401)
            return

        self.room_name = self.scope["url_route"]["kwargs"]["room_name"]
        self.room_group_name = f"chat_{self.room_name}"

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat.message",
                "username": "System",
                "message": f"✅ {user.username} joined room '{self.room_name}'",
                "timestamp": timezone.now().isoformat(),
            },
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data or "{}")
        message = data.get("message", "")
        user = self.scope.get("user")
        username = (
            user.username if getattr(user, "is_authenticated", False) else "Anonymous"
        )

        # Publish to Kafka; broadcaster will fan-out to all pods
        producer = get_kafka_producer()
        payload = {
            "event_id": str(uuid.uuid4()),
            "room": self.room_name,
            "user_id": getattr(user, "id", None),
            "username": username,
            "message": message,
            "timestamp": timezone.now().isoformat(),
        }
        topic = os.getenv("TOPIC_NAME", "chat-messages")
        try:
            producer.send(topic, key=self.room_name, value=payload)
            producer.flush()
        except Exception:
            # Allow dev usage when Kafka is down
            pass

        # Immediate local echo so single-pod dev works without Kafka consumer
        # await self.channel_layer.group_send(
        #     self.room_group_name,
        #     {
        #         "type": "chat.message",
        #         "username": username,
        #         "message": message,
        #         "timestamp": payload["timestamp"],
        #     },
        # )

    async def chat_message(self, event):
        await self._send_event(event)

    async def _send_event(self, event):
        await self.send(text_data=json.dumps({
            "username": event.get("username", "Anonymous"),
            "message": event.get("message", ""),
            "timestamp": event.get("timestamp") or timezone.now().isoformat(),
        }))


