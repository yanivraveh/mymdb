from django.urls import path

from .views import movie_list, movie_details, import_tmdb_movies, rate_movie

app_name = "movies"

urlpatterns = [
    path('', movie_list, name="movie_list"),
    path('movies/<int:pk>/', movie_details, name="movie_details"),
    path('movies/<int:movie_id>/rate/', rate_movie, name="rate_movie"),
    path('import_tmdb_movies/', import_tmdb_movies, name="import_tmdb_movies"),

]