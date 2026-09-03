from django.urls import path

from . import views

app_name = "ledger"

urlpatterns = [
    path("entries/", views.LedgerFeedView.as_view(), name="entries"),
    path("entries/<int:sequence>/explain/", views.LedgerEntryExplainView.as_view(), name="entry-explain"),
]
