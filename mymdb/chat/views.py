from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils.text import slugify
from .models import Room, Message

@require_http_methods(["GET", "POST"])
@login_required
def rooms(request):
    if request.method == "POST":
        name = (request.POST.get("name") or request.GET.get("name") or "").strip()
        if not name:
            return JsonResponse({"error": "name is required"}, status=400)
        slug = slugify(name)
        room, _ = Room.objects.get_or_create(name=name, defaults={"slug": slug, "created_by": request.user})
        if room.slug != slug:
            room.slug = slug
            room.save(update_fields=["slug"])
        return JsonResponse({"id": room.id, "name": room.name, "slug": room.slug})
    # GET list
    data = list(Room.objects.order_by("-created_at").values("id", "name", "slug", "created_at")[:50])
    return JsonResponse({"rooms": data})

@login_required
def room_messages(request, slug):
    # Simple recent history for React hydration
    try:
        room = Room.objects.get(slug=slug)
    except Room.DoesNotExist:
        return JsonResponse({"error": "room not found"}, status=404)
    limit = int(request.GET.get("limit", "50"))
    msgs = Message.objects.filter(room=room).order_by("-created_at")[:max(1, min(200, limit))]
    data = [
        {
            "event_id": str(m.event_id),
            "user_id": m.user_id,
            "username": getattr(m.user, "username", "Anonymous"),
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in msgs
    ]
    return JsonResponse({"room": {"id": room.id, "name": room.name, "slug": room.slug}, "messages": list(reversed(data))})