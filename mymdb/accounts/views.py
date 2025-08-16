from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import  authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm

# Create your views here.

def user_signup(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('/')
    else:
        form = UserCreationForm()
    return render(request, 'accounts/signup.html', {'form': form})

def user_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("/")
        else:
            messages.error(request, 'Invalid username or password.')
            return redirect('accounts:user_login')
    return render(request, 'accounts/login.html')

def user_logout(request):
    logout(request)
    return redirect("/")