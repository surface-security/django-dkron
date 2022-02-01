from django.urls import path, re_path

from . import views

app_name = 'dkron'

urlpatterns = [
    path('auth/', views.auth, name='auth'),
    path('_/', views.proxy, name='proxy'),
    re_path(r'_/(?P<path>.*)$', views.proxy),
]
