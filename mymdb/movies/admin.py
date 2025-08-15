from django.contrib import admin
from .models import Actor, Movie, Director, Genre, Rating, Review

# Register your models here.
admin.site.register(Actor)
admin.site.register(Movie)
admin.site.register(Director)
admin.site.register(Genre)
admin.site.register(Rating)
admin.site.register(Review)

