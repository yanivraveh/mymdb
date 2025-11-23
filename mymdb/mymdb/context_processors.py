from django.conf import settings

def ai_provider(request):
    return {"AI_PROVIDER": getattr(settings, "AI_PROVIDER", "gemini"),
            "CHAT_IFRAME_SRC": getattr(settings, "CHAT_IFRAME_SRC", "http://localhost:5173/"),
    }    