import json
from pathlib import Path
from django.conf import settings
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.parsers import JSONParser, MultiPartParser
from django.shortcuts import render, get_object_or_404, redirect
from django.core.files.storage import default_storage
from .models import Movie, Genre, Director, Actor, Review, Rating
from django.core.paginator import Paginator
from django.db.models import Avg, Count
from urllib.parse import urlencode
from .forms import ReviewForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from . import ai_service
import asyncio
from django.views.decorators.csrf import csrf_exempt
from django.urls import reverse

SORTS = {
    "title_asc": "title",
    "title_desc": "-title",
    "year_asc": "release_year",
    "year_desc": "-release_year",
    # default fallback
    "newest": "-id",
}

@csrf_exempt
def chatbot_api(request):
    if request.method == "POST":
        data = json.loads(request.body)
        user_message = data.get("message")
        history = data.get("history", [])
        
        if not user_message:
            return JsonResponse({"error": "Message is required."}, status=400)
            
        response_data = ai_service.get_chatbot_response(user_message, history=history)
        
        # Add the full URL for each movie, since the AI can't do this
        for movie in response_data.get("movies", []):
            if "id" in movie:
                movie["url"] = request.build_absolute_uri(reverse("movies:movie_details", kwargs={"pk": movie["id"]}))

        return JsonResponse(response_data)
        
    return JsonResponse({"error": "Invalid request method."}, status=405)

# Create your views here.

# Renders the main movie list page with pagination and sorting.
def movie_list(request):
    sort_key = request.GET.get("sort", "newest")
    order_by = SORTS.get(sort_key, SORTS["newest"])

    qs = (Movie.objects
          .select_related('director')
          .prefetch_related('main_actors')
          .order_by(order_by))

    paginator = Paginator(qs, 25)  # 25 per page (Netflix-ish grid)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # build base querystring without the page param so page links don't duplicate it
    base_qs_dict = request.GET.copy()
    base_qs_dict.pop("page", None)
    base_qs = base_qs_dict.urlencode()

    return render(request, "movies/movie_list.html", {
        "page_obj": page_obj,
        "movies": page_obj.object_list,
        "sort_key": sort_key,
        "base_qs": base_qs,
        "sorts": SORTS,  # if you want to render a dropdown
    })


# Renders the detailed view for a single movie, including ratings and reviews.
def movie_details(request, pk):
    movie = get_object_or_404(
        Movie.objects.select_related('director').prefetch_related('main_actors', 'genres'),
        pk=pk
    )
    reviews = Review.objects.filter(movie=movie).select_related('user')
    
    # Get similar movies (based on shared genres)
    current_genres = movie.genres.all()
    similar_movies = Movie.objects.filter(genres__in=current_genres).exclude(pk=pk).distinct().order_by('?')[:5]

    # Rating calculations
    all_ratings = Rating.objects.filter(movie=movie)
    average_rating = all_ratings.aggregate(Avg('score'))['score__avg']
    
    # Rating distribution calculation
    rating_distribution = all_ratings.values('score').annotate(count=Count('score')).order_by('-score')
    total_ratings = all_ratings.count()
    
    distribution_data = {i: 0 for i in range(1, 6)}
    for item in rating_distribution:
        distribution_data[item['score']] = (item['count'] / total_ratings) * 100 if total_ratings > 0 else 0

    user_rating = None
    user_review = None
    if request.user.is_authenticated:
        user_rating = Rating.objects.filter(movie=movie, user=request.user).first()
        user_review = Review.objects.filter(movie=movie, user=request.user).first()

    if request.method == 'POST' and request.user.is_authenticated:
        if 'review_submit' in request.POST:
            if user_review:
                messages.error(request, 'You have already submitted a review for this movie.')
                return redirect('movies:movie_details', pk=movie.pk)

            form = ReviewForm(request.POST) # This is a new submission
            if form.is_valid():
                review = form.save(commit=False)
                review.user = request.user
                review.movie = movie
                review.save()
                messages.success(request, 'Your review has been submitted.')
                return redirect('movies:movie_details', pk=movie.pk)
    else:
        form = ReviewForm() # Always a blank form for GET

    return render(request, 'movies/movie_details.html', {
        'movie': movie,
        'reviews': reviews,
        'average_rating': average_rating,
        'form': form,
        'user_rating': user_rating,
        'user_review': user_review,
        'distribution_data': distribution_data,
        'similar_movies': similar_movies,
    })

# Handles AJAX requests for submitting a movie rating.
@require_POST
def rate_movie(request, movie_id):
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'message': 'You must be logged in to rate a movie.'}, status=401)
    movie = get_object_or_404(Movie, pk=movie_id)
    score = request.POST.get('score')

    if not score:
        return JsonResponse({'status': 'error', 'message': 'Score is required.'}, status=400)

    Rating.objects.update_or_create(
        user=request.user,
        movie=movie,
        defaults={'score': score}
    )
    
    # Recalculate stats
    all_ratings = Rating.objects.filter(movie=movie)
    average_rating = all_ratings.aggregate(Avg('score'))['score__avg'] or 0
    total_ratings = all_ratings.count()
    
    rating_distribution = all_ratings.values('score').annotate(count=Count('score')).order_by('score')
    
    distribution_data = {i: 0 for i in range(1, 6)}
    for item in rating_distribution:
        distribution_data[item['score']] = (item['count'] / total_ratings) * 100 if total_ratings > 0 else 0

    return JsonResponse({
        'status': 'success',
        'message': 'Your rating has been submitted.',
        'new_average_rating': round(average_rating, 1),
        'new_distribution': distribution_data
    })

# A helper function to split a full name into first and last names.
def split_name(fullname: str) -> tuple[str, str]:
    parts = (fullname or "").strip().split()
    if not parts: return ("", "")
    if len(parts) == 1: return (parts[0], "")
    return (" ".join(parts[:-1]), parts[-1])

# An admin-only API endpoint for importing movie data from a JSON file.
@api_view(["POST"])
@permission_classes([IsAdminUser])
@parser_classes([JSONParser, MultiPartParser])
def import_tmdb_movies(request):
    # Accept uploaded file (field "file") OR JSON body (single movie or list)
    try:
        if "file" in request.FILES:
            data = json.load(request.FILES["file"])
        else:
            data = request.data
            if isinstance(data, dict):
                data = [data]
    except Exception as e:
        return JsonResponse({"error": f"Invalid JSON: {e}"}, status=400)

    if not isinstance(data, list):
        return JsonResponse({"error": "Expected a JSON array or one JSON object."}, status=400)

    media_root = Path(getattr(settings, "MEDIA_ROOT", "media"))

    created_movies = updated_movies = 0
    created_genres = created_directors = created_actors = 0
    missing_poster_files = 0
    errors = []

    for idx, item in enumerate(data, start=1):
        try:
            title = (item.get("title") or "").strip()
            if not title:
                raise ValueError("Missing title")

            try:
                release_year = int(item.get("release_year") or 0)
            except Exception:
                release_year = 0

            description = item.get("description") or ""
            director_name = (item.get("director") or "").strip()

            # Director
            fn, ln = split_name(director_name) if director_name else ("", "")
            director, d_created = Director.objects.get_or_create(first_name=fn, last_name=ln)
            if d_created: created_directors += 1

            # Movie (upsert by title + year)
            movie, was_created = Movie.objects.get_or_create(
                title=title,
                release_year=release_year,
                defaults={"description": description, "director": director},
            )
            if was_created:
                created_movies += 1
            else:
                changed = False
                if movie.description != description:
                    movie.description = description; changed = True
                if movie.director_id != director.id:
                    movie.director = director; changed = True
                if changed:
                    movie.save(); updated_movies += 1

            # Poster (relative path like "posters/xyz.jpg")
            poster_rel = item.get("poster")
            if poster_rel:
                if default_storage.exists(poster_rel) and movie.poster.name != poster_rel:
                    movie.poster.name = poster_rel
                    movie.save(update_fields=["poster"])
                elif not default_storage.exists(poster_rel):
                    missing_poster_files += 1

            # Genres
            for gname in (item.get("genres") or []):
                gname = (gname or "").strip()
                if not gname: continue
                genre, g_created = Genre.objects.get_or_create(name=gname)
                if g_created: created_genres += 1
                movie.genres.add(genre)

            # Main actors (cap 4, replace set)
            actor_objs = []
            for full in (item.get("main_actors") or [])[:4]:
                a_fn, a_ln = split_name(full)
                actor, a_created = Actor.objects.get_or_create(first_name=a_fn, last_name=a_ln)
                if a_created: created_actors += 1
                actor_objs.append(actor)
            movie.main_actors.set(actor_objs)

        except Exception as e:
            errors.append({"index": idx, "title": item.get("title"), "error": str(e)})

    payload = {
        "movies_created": created_movies,
        "movies_updated": updated_movies,
        "new_genres_created": created_genres,
        "new_directors_created": created_directors,
        "new_actors_created": created_actors,
        "missing_poster_files": missing_poster_files,
        "errors": errors,
        "total_incoming": len(data),
    }
    return JsonResponse(payload, status=201 if (created_movies or updated_movies) else 200, json_dumps_params={"indent": 2})
