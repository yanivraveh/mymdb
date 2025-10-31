import json, os, threading, uuid
from kafka import KafkaConsumer
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

def start_kafka_broadcaster():
    # Guard to avoid double-start in dev reloads
    if getattr(start_kafka_broadcaster, "_started", False):
        return
    start_kafka_broadcaster._started = True

    bootstrap = os.getenv("BOOTSTRAP_SERVERS", "localhost:29092")
    topic = os.getenv("TOPIC_NAME", "chat-messages")
    group_id = os.getenv("GROUP_ID") or f"django-asgi-{uuid.uuid4()}"

    def run():
        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=bootstrap,
            auto_offset_reset="earliest",
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            group_id=group_id,
            enable_auto_commit=True,
        )
        layer = get_channel_layer()
        for msg in consumer:
            payload = msg.value or {}
            room = payload.get("room")
            if not room:
                continue
            async_to_sync(layer.group_send)(
                f"chat_{room}",
                {
                    "type": "chat.message",
                    "username": payload.get("username") or "Anonymous",
                    "message": payload.get("message") or "",
                    "timestamp": payload.get("timestamp"),
                },
            )

    t = threading.Thread(target=run, name="kafka-broadcaster", daemon=True)
    t.start()