import json, boto3
import logging
from functools import reduce
from operator import or_
import google.generativeai as genai
from django.db.models import Q

from mymdb import settings
from .models import Movie

logger = logging.getLogger(__name__)

# This list is used to extract meaningful keywords from a user's query.
STOP_WORDS = {
    'a', 'about', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
    'how', 'i', 'in', 'is', 'it', 'of', 'on', 'or', 'that', 'the', 'this',
    'to', 'was', 'what', 'when', 'where', 'who', 'will', 'with', 'the',
    'give', 'me', 'show', 'movies', 'movie', 'some', 'find', 'recommend',
    'please', 'want'
}

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
You are "MyDBot", a witty and knowledgeable movie expert.
Your job is to generate a friendly, conversational response based on the user's request and the context provided.
- Your response must be a single JSON object with one key: "text".

- If a list of "movies_found" is provided, present up to 3 of them to the user in a fun, brief, and conversational way.
- If NO "movies_found" list is provided, simply have a natural, witty conversation with the user based on their message.
- If the user's intent was "summarize_history", present the provided movie list as a summary of what has been discussed.
- If you receive a "special_instruction", prioritize following it. For example, if asked to deflect, do so with a witty, movie-related comment.
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

def _gemini_response(user_message: str, history: list = None):
    if not settings.GEMINI_API_KEY:
        return {"text": "Sorry, the chatbot is currently unavailable.", "movies": []}

    try:
        # Step 1: AI Parser - Determine the user's intent.
        genai.configure(api_key=settings.GEMINI_API_KEY)
        parser_model = genai.GenerativeModel(model_name='gemini-2.0-flash-lite-001',
                                            system_instruction=PARSER_SYSTEM_INSTRUCTION)

        parser_prompt = f"""
            Conversation History: {json.dumps(history)}
            Latest User Request: "{user_message}"
        """
        parser_response = parser_model.generate_content(parser_prompt)

        # Sanitize the response to ensure it's valid JSON
        criteria_text = parser_response.text.strip().replace("```json", "```").replace("```", "")
        parsed_response = json.loads(criteria_text)
        intent = parsed_response.get("intent")
        criteria = parsed_response.get("criteria", {})

        found_movies = []
        movies_to_present = []
        conversational_context = {}

        if intent == "search_movies":
            query_parts = []

            # Apply filters from the parsed criteria
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
                    # This is a simple split; won't handle middle names well but is good for a start.
                    parts = actor_name.split()
                    if len(parts) > 1:
                        actor_query |= (Q(main_actors__first_name__icontains=parts[0]) & Q(main_actors__last_name__icontains=parts[-1]))
                    else:
                        actor_query |= (Q(main_actors__first_name__icontains=actor_name) | Q(main_actors__last_name__icontains=actor_name))
                if actor_query:
                    query_parts.append(actor_query)

            if criteria.get("director"):
                director_query = Q()
                # Assuming director is a single name for now
                director_name = criteria["director"]
                parts = director_name.split()
                if len(parts) > 1:
                    director_query |= (Q(director__first_name__icontains=parts[0]) & Q(director__last_name__icontains=parts[-1]))
                else:
                    director_query |= (Q(director__first_name__icontains=director_name) | Q(director__last_name__icontains=director_name))
                if director_query:
                    query_parts.append(director_query)

            if criteria.get("keywords"):
                search_keywords = [word for word in " ".join(criteria["keywords"]).split() if
                                   word.lower() not in STOP_WORDS]
                if search_keywords:
                    keyword_query = reduce(or_,
                                           [Q(title__icontains=kw) | Q(description__icontains=kw) for kw in
                                            search_keywords])
                    query_parts.append(keyword_query)

            if not query_parts:
                return {"text": "I'm sorry, I couldn't understand what to search for. Could you be more specific?",
                        "movies": []}

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
            previously_shown_movies = []
            if history:
                for turn in history:
                    if turn.get('role') == 'model':
                        try:
                            model_message_str = turn['parts'][0]['text']
                            model_message_obj = json.loads(model_message_str)
                            if 'movies' in model_message_obj and model_message_obj['movies']:
                                previously_shown_movies.extend(model_message_obj['movies'])
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue  # Ignore malformed history items

            seen_ids = set()
            unique_movies = []
            for movie in previously_shown_movies:
                if movie['id'] not in seen_ids:
                    unique_movies.append(movie)
                    seen_ids.add(movie['id'])

            movies_to_present = unique_movies
            conversational_context["movies_found"] = movies_to_present
            if not movies_to_present:
                conversational_context[
                    "special_instruction"] = "The user asked for a summary, but no movies have been recommended yet. Inform them of this politely."

        elif intent == "off_topic":
            conversational_context[
                "special_instruction"] = "The user's question is off-topic. Gently deflect it with a witty, movie-related comment without answering it."

        # Step 2: AI Conversationalist - Generate a friendly response.
        conversational_model = genai.GenerativeModel(model_name='gemini-2.0-flash-lite-001',
                                                    system_instruction=CONVERSATIONALIST_SYSTEM_INSTRUCTION)

        final_prompt = f"""
            User's original request: "{user_message}"
            Conversation History: {json.dumps(history)}
            User's Intent: "{intent}"
            Context: {json.dumps(conversational_context)}
        """
        final_response = conversational_model.generate_content(final_prompt)
        response_json_text = final_response.text.strip().replace("```json", "```").replace("```", "")
        response_data = json.loads(response_json_text)

        response_data["movies"] = movies_to_present

        return response_data

    except Exception as e:
        error_message = f"Error in chatbot response generation: {e}"
        logger.error(error_message)
        if "429" in error_message:
            return {"text": "Sorry, the quota for the AI service has been reached. Please check with your administrator or review your billing settings.", "movies": []}
        return {"text": f"Sorry, I had trouble processing that request ({e}). Could you try rephrasing?", "movies": []}
