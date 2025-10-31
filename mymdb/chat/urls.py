from django.urls import path
from . import views

urlpatterns = [
    path("rooms/", views.rooms, name="chat_rooms"),
    path("rooms/<slug:slug>/messages/", views.room_messages, name="chat_room_messages"),
]