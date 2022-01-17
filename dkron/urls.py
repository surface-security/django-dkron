from django.urls import path

from . import views

app_name = 'dkron'

urlpatterns = [path('auth/', views.auth, name='auth')]
