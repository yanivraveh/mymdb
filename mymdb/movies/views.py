import json
from pathlib import Path
from django.conf import settings
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.parsers import JSONParser, MultiPartParser
from django.shortcuts import render, get_object_or_404
from .models import Movie, Genre, Director, Actor
from django.core.paginator import Paginator
from urllib.parse import urlencode

SORTS = {
    "title_asc": "title",
    "title_desc": "-title",
    "year_asc": "release_year",
    "year_desc": "-release_year",
    # default fallback
    "newest": "-id",
}

# Create your views here.

def movie_list(request):
    sort_key = request.GET.get("sort", "newest")
    order_by = SORTS.get(sort_key, SORTS["newest"])

    qs = (Movie.objects
          .select_related('director')
          .prefetch_related('main_actors')
          .order_by(order_by))

    paginator = Paginator(qs, 24)  # 24 per page (Netflix-ish grid)
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



def movie_details(request, pk):
    movie = get_object_or_404(
        Movie.objects.select_related('director').prefetch_related('main_actors'),
        pk=pk
    )
    return render(request, 'movies/movie_details.html', {'movie': movie})

def split_name(fullname: str) -> tuple[str, str]:
    parts = (fullname or "").strip().split()
    if not parts: return ("", "")
    if len(parts) == 1: return (parts[0], "")
    return (" ".join(parts[:-1]), parts[-1])

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
                poster_path = media_root / poster_rel
                if poster_path.is_file() and movie.poster.name != poster_rel:
                    movie.poster.name = poster_rel
                    movie.save(update_fields=["poster"])
                elif not poster_path.is_file():
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
