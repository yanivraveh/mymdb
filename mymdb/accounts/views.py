from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import  authenticate, login, logout
from django.contrib import messages

# Create your views here.

def user_signup(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        password2 = request.POST.get('password2')

        if password != password2:
            messages.error(request, 'Passwords do not match.')
            return redirect('accounts:user_signup')

        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already taken.')
            return redirect('accounts:user_signup')

        user = User.objects.create_user(username=username, email=email, password=password)
        login(request, user)
        return redirect('/')

    return render(request, 'accounts/signup.html')

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