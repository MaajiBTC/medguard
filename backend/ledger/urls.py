from django.urls import path

from . import views

app_name = "ledger"

urlpatterns = [
    path("entries/", views.LedgerFeedView.as_view(), name="entries"),
    path("my-activity/", views.MyActivityCalendarView.as_view(), name="my-activity"),
    path("entries/<int:sequence>/explain/", views.LedgerEntryExplainView.as_view(), name="entry-explain"),
    path("verify/", views.LedgerVerifyView.as_view(), name="verify"),
]
