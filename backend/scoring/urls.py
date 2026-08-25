from django.urls import path

from . import views

app_name = "scoring"

urlpatterns = [
    path("decide/", views.DecideView.as_view(), name="decide"),
]
