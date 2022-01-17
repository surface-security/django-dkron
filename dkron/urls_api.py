from django.urls import path

from . import views

app_name = 'dkron_api'

urlpatterns = [path('webhook/', views.webhook, name='webhook')]
