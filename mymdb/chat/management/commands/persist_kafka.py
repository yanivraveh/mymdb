from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from django.db import IntegrityError
from kafka import KafkaConsumer
from chat.models import Room, Message
import json, os, uuid

User = get_user_model()

class Command(BaseCommand):
    help = "Consume chat-messages and persist to DB with idempotency"

    def handle(self, *args, **options):
        bootstrap = os.getenv("BOOTSTRAP_SERVERS", "localhost:29092")
        topic = os.getenv("TOPIC_NAME", "chat-messages")
        # One persister group globally; do NOT make this unique per pod
        group_id = os.getenv("PERSIST_GROUP_ID", "chat-db-writer")

        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=bootstrap,
            auto_offset_reset="earliest",
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            group_id=group_id,
            enable_auto_commit=True,
        )

        self.stdout.write(self.style.SUCCESS(f"[persist] {bootstrap} topic={topic} group={group_id}"))

        for msg in consumer:
            payload = msg.value or {}
            event_id = payload.get("event_id")
            room_name = payload.get("room")
            username = payload.get("username") or "Anonymous"
            user_id = payload.get("user_id")
            content = payload.get("message") or ""

            if not room_name or not event_id:
                continue

            # Upsert room by name/slug
            room_slug = payload.get("room")  # this is already the slug from WS URL
            if not room_slug:
                continue

            # Prefer existing room by slug
            room = Room.objects.filter(slug=room_slug).first()
            if not room:
                display_name = payload.get("room_display") or room_slug.replace("-", " ")
                try:
                    room = Room.objects.create(name=display_name, slug=room_slug)
                except IntegrityError:
                    room = Room.objects.get(slug=room_slug)

            # Resolve user (optional)
            user = None
            if user_id:
                try:
                    user = User.objects.get(id=user_id)
                except User.DoesNotExist:
                    user = None

            # Idempotent insert by event_id unique constraint
            try:
                Message.objects.create(
                    event_id=uuid.UUID(event_id),
                    room=room,
                    user=user,
                    content=content,
                )
            except Exception:
                # duplicate or invalid – skip
                continue