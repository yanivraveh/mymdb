from django.conf import settings

def ai_provider(request):
    return {"AI_PROVIDER": getattr(settings, "AI_PROVIDER", "gemini")}