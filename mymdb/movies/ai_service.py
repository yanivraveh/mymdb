import json, boto3
import os
import logging
from functools import reduce
from operator import or_
import google.generativeai as genai
from django.db.models import Q

from mymdb import settings
from .models import Movie
from . import rag_index
import re
from collections import Counter


logger = logging.getLogger(__name__)

# This list is used to extract meaningful keywords from a user's query.
STOP_WORDS = {
    'a', 'about', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
    'how', 'i', 'in', 'is', 'it', 'of', 'on', 'or', 'that', 'the', 'this',
    'to', 'was', 'what', 'when', 'where', 'who', 'will', 'with', 'the',
    'give', 'me', 'show', 'movies', 'movie', 'some', 'find', 'recommend',
    'please', 'want'
}

def extract_topic_hint(message: str) -> str:
    m = message.strip()
    # Try phrases after cue words
    mlow = m.lower()
    for cue in ["about", "with", "featuring", "related to", "on", "around"]:
        if cue in mlow:
            after = m[mlow.find(cue) + len(cue):].strip(" ?.!:,;-")
            if after:
                return after[:40]
    # Fallback: take 1–2 non-stopwords
    import re
    words = [w for w in re.findall(r"\w+", m) if w.lower() not in STOP_WORDS]
    return " ".join(words[:2])[:40] if words else ""

def detect_intent(user_message: str) -> str:
    m = user_message.strip().lower()
    if re.search(r'\b(summary|summarize|recap|what.*shown)\b', m):
        return "summary"
    if re.search(r'\b(more|another|others|more please|more!)\b', m):
        return "more"
    # phrase cues that imply a topical search
    if re.search(r'\b(do you have|about|with|featuring|related to|on)\b', m):
        return "search"
    # heuristic “search” cues
    genres = {"action","comedy","drama","horror","thriller","romance","sci-fi","science fiction","fantasy","animation",
              "crime","western","war","documentary","adventure","mystery","family"}
    if (any(g in m for g in genres)
        or re.search(r'\b(movie|movies|film|films|recommend|show)\b', m)
        or re.search(r'\b(19\d0s|20\d0s|\d{4})\b', m)
        or re.search(r'\b(director|actor|starring|by)\b', m)):
        return "search"
    return "off_topic"

GENRE_KEYWORDS = {"action","comedy","drama","horror","thriller","romance","sci-fi","science fiction","fantasy",
                  "animation","crime","western","war","documentary","adventure","mystery","family"}

def extract_genres(message: str) -> set[str]:
    m = message.lower()
    return {g for g in GENRE_KEYWORDS if g in m}    

def collect_shown_ids(history: list | None) -> set[int]:
    shown = set()
    if not history: 
        return shown
    for turn in history:
        if turn.get('role') == 'model':
            try:
                obj = json.loads(turn['parts'][0]['text'])
                for m in obj.get('movies', []):
                    if 'id' in m:
                        shown.add(m['id'])
            except Exception:
                continue
    return shown

PARSER_SYSTEM_INSTRUCTION = """
You are an Intent Classification expert. Your ONLY job is to analyze the user's text and the conversation history to determine the user's primary goal.
- Your response MUST be a single, valid JSON object and nothing else.
- The JSON object must have a single key, "intent", and may have "criteria" if the intent is "search_movies".

Possible intents are:
- "search_movies": The user is asking for movie recommendations or searching for specific movies. Extract genres, keywords, release_year, actors, and directors into a "criteria" object. Also, identify already recommended movie IDs from the history and add them to "criteria.exclude_ids". For decades (e.g., "80s", "1990s"), convert it to a "release_year" object with "start" and "end" years.
- "summarize_history": The user is asking a question about the conversation history itself (e.g., "what have you shown me?", "did you mention inception?").
- "general_conversation": The user is making small talk, asking about your preferences, or having a general chat that is still movie-related but isn't a direct search request.
- "off_topic": The user's request is not related to movies at all.

Crucial Rule for Follow-up Searches:
- If the user's intent is `search_movies` but their latest request is vague (e.g., "give me more", "any others?"), you MUST look at the conversation history to infer the search criteria from the previous successful search. Re-use the same genres, keywords, etc.

Example 1:
User: "show me wwii movies"
{
  "intent": "search_movies",
  "criteria": {
    "keywords": ["wwii"],
    "exclude_ids": [12, 34]
  }
}

Example 2:
User: "which movies have you already recommended?"
{
  "intent": "summarize_history"
}

Example 3:
User: "Hi there!"
{
  "intent": "general_conversation"
}

Example 4 (Follow-up):
Conversation History: [{"role": "user", "parts": [{"text": "{\"message\": \"i want a comedy\"}"}]}, {"role": "model", "parts": [{"text": "{\"text\": \"...\", \"movies\": [{\"id\": 1, \"title\": \"Comedy A\"}]}"}]}]
Latest User Request: "give me some more"
{
  "intent": "search_movies",
  "criteria": {
    "genres": ["Comedy"],
    "exclude_ids": [1]
  }
}

Example 5 (Decade Search):
User: "movies from the 70s"
{
  "intent": "search_movies",
  "criteria": {
    "release_year": {
      "start": 1970,
      "end": 1979
    }
  }
}
"""

CONVERSATIONALIST_SYSTEM_INSTRUCTION = """
You are MyMDBot, a witty and knowledgeable movie recommendation assistant.
Your job is to generate a friendly, conversational response based on the user's request and the context provided.
Return only a single JSON object: {"text": "..."}.

Rules:
- If movies_found is provided and relevant to the user’s request, briefly recommend up to 3 (1 short line each, no spoilers). Do not invent titles; use only movies_found.
- If movies_found is empty OR the user’s request is off-topic (not about movies), do NOT recommend. Politely say you can help with movie recommendations and ask a clarifying question (e.g., genre, decade, actor, or director).
- If the user asks for “more” without new criteria, suggest clarifying what to change (e.g., “more comedies from the 90s?”). Do not repeat the same titles.
- If the user asks to summarize what was shown, keep it brief (“We discussed X, Y, Z.”). If none, say so.
- If special_instruction is provided, follow it strictly and do not recommend unless it says so.
- If topic_hint is provided, reflect it in the wording (e.g., ‘…about {topic_hint}’) and vary phrasing; avoid repeating the same sentence.
- Keep replies under ~60 words. Friendly, concise, no spoilers, no extra JSON fields.
"""

def _try_parse_json(txt: str):
    cleaned = txt.strip().replace("```json", "```").replace("```", "")
    try:
        return json.loads(cleaned)
    except Exception:
        return None

def get_chatbot_response(user_message: str, history: list = None):
    if settings.AI_PROVIDER == "bedrock":
        return _bedrock_response(user_message, history)
    return _gemini_response(user_message, history)

def _bedrock_completion(system_text: str, user_text: str) -> str:
    client = boto3.client("bedrock-runtime", region_name=settings.AWS_REGION)
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "temperature": 0.7,
        "messages": [{"role": "user", "content": [{"type": "text", "text": user_text}]}],
        "system": [{"type": "text", "text": system_text}],
    }
    out = client.invoke_model(
        modelId=settings.BEDROCK_MODEL_ID,
        accept="application/json",
        contentType="application/json",
        body=json.dumps(body),
    )
    payload = json.loads(out["body"].read())
    return "".join(block.get("text","") for block in payload.get("content", []) if block.get("type") == "text")

def _bedrock_response(user_message: str, history: list = None):
    # 1) Parser → must return JSON
    parser_prompt = f"""
        Conversation History: {json.dumps(history)}
        Latest User Request: "{user_message}"
    """
    criteria_text = _bedrock_completion(PARSER_SYSTEM_INSTRUCTION, parser_prompt)
    criteria_text = criteria_text.strip().replace("```json", "```").replace("```", "")
    criteria_obj = _try_parse_json(criteria_text)
    if not criteria_obj:
        intent, criteria = "general_conversation", {}
    else:
        intent = criteria_obj.get("intent")
        criteria = criteria_obj.get("criteria", {})

    # 2) Reuse your existing DB filtering block exactly as in Gemini
    #    Build found_movies, movies_to_present, conversational_context = {...}
    #    (You can extract that block into a shared helper to avoid duplication.)
    found_movies = []
    movies_to_present = []
    conversational_context = {}

    if intent == "search_movies":
        query_parts = []

        if criteria.get("genres"):
            for genre in criteria["genres"]:
                query_parts.append(Q(genres__name__icontains=genre))

        if criteria.get("release_year"):
            year_value = criteria["release_year"]
            if isinstance(year_value, dict) and "start" in year_value and "end" in year_value:
                query_parts.append(Q(release_year__gte=year_value["start"], release_year__lte=year_value["end"]))
            elif isinstance(year_value, int):
                query_parts.append(Q(release_year=year_value))

        if criteria.get("actors"):
            actor_query = Q()
            for actor_name in criteria["actors"]:
                parts = actor_name.split()
                if len(parts) > 1:
                    actor_query |= (Q(main_actors__first_name__icontains=parts[0]) & Q(main_actors__last_name__icontains=parts[-1]))
                else:
                    actor_query |= (Q(main_actors__first_name__icontains=actor_name) | Q(main_actors__last_name__icontains=actor_name))
            if actor_query:
                query_parts.append(actor_query)

        if criteria.get("director"):
            director_query = Q()
            director_name = criteria["director"]
            parts = director_name.split()
            if len(parts) > 1:
                director_query |= (Q(director__first_name__icontains=parts[0]) & Q(director__last_name__icontains=parts[-1]))
            else:
                director_query |= (Q(director__first_name__icontains=director_name) | Q(director__last_name__icontains=director_name))
            if director_query:
                query_parts.append(director_query)

        if criteria.get("keywords"):
            search_keywords = [w for w in " ".join(criteria["keywords"]).split() if w.lower() not in STOP_WORDS]
            if search_keywords:
                keyword_query = reduce(or_, [Q(title__icontains=kw) | Q(description__icontains=kw) for kw in search_keywords])
                query_parts.append(keyword_query)

        if not query_parts:
            return {"text": "I'm sorry, I couldn't understand what to search for. Could you be more specific?", "movies": []}

        final_query = reduce(or_, query_parts)
        query_set = Movie.objects.filter(final_query)
        if criteria.get("exclude_ids"):
            query_set = query_set.exclude(id__in=criteria["exclude_ids"])

        found_movies = list(query_set.distinct().values("id", "title", "release_year", "description")[:10])
        movies_to_present = found_movies[:3]
        conversational_context["movies_found"] = movies_to_present
        if not found_movies:
            conversational_context["special_instruction"] = "The user searched for movies, but none were found in the database. Inform them of this politely."



    elif intent == "summarize_history":
        previously_shown = []
        if history:
            for turn in history:
                if turn.get('role') == 'model':
                    try:
                        model_message_str = turn['parts'][0]['text']
                        obj = json.loads(model_message_str)
                        if 'movies' in obj and obj['movies']:
                            previously_shown.extend(obj['movies'])
                    except Exception:
                        continue
        seen = set()
        unique = []
        for m in previously_shown:
            if m['id'] not in seen:
                unique.append(m); seen.add(m['id'])
        movies_to_present = unique
        conversational_context["movies_found"] = movies_to_present
        if not movies_to_present:
            conversational_context["special_instruction"] = "The user asked for a summary, but no movies have been recommended yet. Inform them of this politely."
    elif intent == "off_topic":
        conversational_context["special_instruction"] = "The user's question is off-topic. Gently deflect..."

    # 3) Conversationalist → returns {"text": "..."} JSON per your instruction
    final_prompt = f"""
        User's original request: "{user_message}"
        Conversation History: {json.dumps(history)}
        User's Intent: "{intent}"
        Context: {json.dumps(conversational_context)}
    """
    response_json_text = _bedrock_completion(CONVERSATIONALIST_SYSTEM_INSTRUCTION, final_prompt)
    response_json_text = response_json_text.strip().replace("```json", "```").replace("```", "")
    data = _try_parse_json(response_json_text)
    if not data:
        fallback = "Here are some movies you might like:" if movies_to_present else "Sorry, I had trouble formatting the response."
        data = {"text": fallback, "movies": movies_to_present}
    else:
        data["movies"] = movies_to_present
    return data

def _keyword_db_fallback(user_message: str, top_k: int = 5):
    """Simple keyword-only DB search as a safety net (no LLM)."""
    search_keywords = [w for w in user_message.split() if w.lower() not in STOP_WORDS]
    if not search_keywords:
        return []
    keyword_query = reduce(or_, [Q(title__icontains=kw) | Q(description__icontains=kw) for kw in search_keywords])
    qs = Movie.objects.filter(keyword_query).distinct().values("id", "title", "release_year", "description")[: top_k]
    return list(qs)


def _gemini_response(user_message: str, history: list = None):
    if not settings.GEMINI_API_KEY:
        return {"text": "Sorry, the chatbot is currently unavailable.", "movies": []}

    try:
        # Configure Gemini (one-call conversationalist)
        genai.configure(api_key=settings.GEMINI_API_KEY)

        # RAG retrieval via FAISS (no Gemini embeddings)
        top_k = int(os.getenv("RAG_TOP_K", "5"))
        max_docs = int(os.getenv("RAG_MAX_DOCS", "500"))
        embed_model = os.getenv("RAG_EMBED_MODEL", "all-MiniLM-L6-v2")

        intent = detect_intent(user_message)
        shown_ids = collect_shown_ids(history)
        topic_hint = extract_topic_hint(user_message)
        
        requested_genres = extract_genres(user_message)
        cap_genres = [g.capitalize() for g in requested_genres]  # DB genres are capitalized        

        # If user said “more” but didn’t specify genres, infer from previously shown items
        if intent == "more" and not cap_genres and shown_ids:
            counts = Counter()
            for m in Movie.objects.filter(id__in=shown_ids).prefetch_related("genres"):
                for g in m.genres.all():
                    counts[g.name] += 1
            # Take the top 1–2 genres as the inferred preference
            cap_genres = [name for name, _ in counts.most_common(2)]

        movies_to_present = []

        # Always try RAG for any non-empty message, but gate by similarity
        ids, scores = rag_index.retrieve_with_scores(user_message, top_k=top_k, model_name=embed_model, max_docs=max_docs)

        logger.info(f"FAISS index size={rag_index.index_size()} retrieved={len(ids)} top_scores={scores[:3]}")

        movies_to_present = []
        min_sim = float(os.getenv("RAG_MIN_SIM", "0.25"))  # cosine on normalized vectors ∈ [-1,1]

        if ids and max(scores or [0.0]) >= min_sim:
            id_to_rank = {mid: i for i, mid in enumerate(ids)}
            base_qs = Movie.objects.filter(id__in=ids)
            if cap_genres:
                base_qs = base_qs.filter(genres__name__in=cap_genres)
            rows = list(base_qs.distinct().values("id","title","release_year","description"))
            if intent == "more" and shown_ids:
                rows = [r for r in rows if r["id"] not in shown_ids]
            rows.sort(key=lambda m: id_to_rank.get(m["id"], 10_000))
            movies_to_present = rows[: min(3, len(rows))]

        # If user explicitly asked for search/more and RAG came up empty, try keyword fallback
        if intent in ("search","more") and not movies_to_present:
            fallback_rows = _keyword_db_fallback(user_message, top_k=top_k)
            if intent == "more" and shown_ids:
                fallback_rows = [r for r in fallback_rows if r["id"] not in shown_ids]
            if cap_genres and fallback_rows:
                fallback_qs = Movie.objects.filter(
                    id__in=[r["id"] for r in fallback_rows],
                    genres__name__in=cap_genres,
                )
                fallback_rows = list(
                    fallback_qs.distinct().values("id","title","release_year","description")
                )
            if fallback_rows:
                movies_to_present = fallback_rows[: min(3, len(fallback_rows))]

        # Summary overrides: show up to 3 previously shown
        if intent == "summary":
            if shown_ids:
                rows = list(
                    Movie.objects.filter(id__in=shown_ids).values("id","title","release_year","description")
                )
                movies_to_present = rows[: min(3, len(rows))]
        conversational_context = {}
        if movies_to_present and intent in ("search","more","summary"):
            conversational_context["movies_found"] = movies_to_present
        else:
            conversational_context["special_instruction"] = (
                "The request is off-topic or vague. Ask a short clarifying question (genre, decade, actor, or director) and do not recommend yet."
            )
        if topic_hint:
            conversational_context["topic_hint"] = topic_hint

        model = genai.GenerativeModel(
            model_name='gemini-2.0-flash-lite-001',
            system_instruction=CONVERSATIONALIST_SYSTEM_INSTRUCTION,
        )
        final_prompt = f"""
            User's original request: "{user_message}"
            Conversation History: {json.dumps(history)}
            Context: {json.dumps(conversational_context)}
        """
        final_response = model.generate_content(final_prompt)
        response_text = final_response.text.strip().replace("```json", "```").replace("```", "")
        data = _try_parse_json(response_text)
        if not data:
            fallback = "Here are some movies you might like:" if movies_to_present else "Sorry, I had trouble formatting the response."
            data = {"text": fallback}
        data["movies"] = movies_to_present
        return data

    except Exception as e:
        error_message = f"Error in chatbot response generation: {e}"
        logger.error(error_message)
        if "429" in error_message:
            return {"text": "Sorry, the quota for the AI service has been reached. Please check with your administrator or review your billing settings.", "movies": []}
        return {"text": f"Sorry, I had trouble processing that request ({e}). Could you try rephrasing?", "movies": []}
