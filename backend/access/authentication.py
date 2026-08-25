from rest_framework import authentication, exceptions

from .models import AccessSession


class AccessSessionAuthentication(authentication.BaseAuthentication):
    """Resolves `Authorization: Bearer <token>` to an active AccessSession.

    Chosen over Django's cookie sessions or DRF's built-in TokenAuthentication because
    the domain concept is genuinely "one token = one login session" (not one permanent
    token per user), and it sidesteps CORS/CSRF friction between the two local dev
    servers (Django on 8000, Vite on 5173). Django admin keeps using its own normal
    session auth, untouched by this class.

    On success returns (user, session) — DRF exposes these as request.user and
    request.auth, so views reach the session via request.auth.
    """

    keyword = "bearer"

    def authenticate(self, request):
        auth_header = authentication.get_authorization_header(request).decode("utf-8")
        if not auth_header:
            return None

        parts = auth_header.split()
        if not parts or parts[0].lower() != self.keyword:
            return None

        if len(parts) == 1:
            raise exceptions.AuthenticationFailed("Invalid Authorization header: no token provided.")
        if len(parts) > 2:
            raise exceptions.AuthenticationFailed("Invalid Authorization header: token must not contain spaces.")

        token = parts[1]

        try:
            session = AccessSession.objects.select_related("staff", "staff__user").get(
                token=token, is_active=True
            )
        except AccessSession.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid or inactive session token.")

        return (session.staff.user, session)

    def authenticate_header(self, request):
        return "Bearer"
