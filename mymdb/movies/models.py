from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator


# Create your models here.

class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Director(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    def __str__(self):
        return self.first_name + " " + self.last_name

class Actor(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    def __str__(self):
        return f'{self.first_name} {self.last_name}'


class Movie(models.Model):
    title = models.CharField(max_length=100)
    poster = models.ImageField(upload_to="posters/", null=True, blank=True)
    description = models.TextField()
    # director = models.CharField(max_length=100)
    director = models.ForeignKey(Director, on_delete=models.CASCADE)
    release_year = models.IntegerField()
    main_actors = models.ManyToManyField(Actor, related_name='movies') # 'movies' instead of default 'movie_set'
    genres = models.ManyToManyField(Genre, related_name="movies", blank=True)


    def __str__(self):
        return self.title


class Rating(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ratings")
    movie = models.ForeignKey("Movie", on_delete=models.CASCADE, related_name="ratings")
    score = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "movie"], name="unique_rating_per_user_movie"),
        ]
        indexes = [models.Index(fields=["movie", "score"])]

    def __str__(self):
        return f"{self.user} → {self.movie} = {self.score}"


class Review(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    movie = models.ForeignKey("Movie", on_delete=models.CASCADE, related_name="reviews")
    title = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "movie"], name="unique_review_per_user_movie"),
        ]
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["movie", "created_at"])]

    def __str__(self):
        return f"Review by {self.user} on {self.movie}"
