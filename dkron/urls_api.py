from django.urls import path

from . import views

app_name = 'dkron_api'

urlpatterns = [
    path('pre-webhook/', views.pre_webhook, name='pre_webhook'),
    path('webhook/', views.webhook, name='webhook'),
]
