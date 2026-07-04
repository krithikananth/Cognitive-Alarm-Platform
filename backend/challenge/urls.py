from django.urls import path
from . import views

urlpatterns = [
    path('', views.challenge_list, name='challenge'),
    path('page/', views.challenge_page, name='challenge_page'),
]