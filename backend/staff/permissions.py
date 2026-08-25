from rest_framework.permissions import BasePermission

from access.models import AccessSession

from .models import Staff


class _HasRole(BasePermission):
    """Base for role-gated endpoints. `request.auth` is the AccessSession (see
    access.authentication.AccessSessionAuthentication) -- these checks are on top of
    the default IsAuthenticated, not instead of it.
    """

    role = None

    def has_permission(self, request, view):
        session = request.auth
        return isinstance(session, AccessSession) and session.staff.role == self.role


class IsAdmin(_HasRole):
    role = Staff.Role.ADMIN


class IsSecurityOfficer(_HasRole):
    role = Staff.Role.SECURITY_OFFICER


class IsClinicalStaff(BasePermission):
    """Doctor/nurse/pharmacist/lab technician/clerk -- roles the Scoring Engine
    actually grants patient-record categories to."""

    def has_permission(self, request, view):
        session = request.auth
        return isinstance(session, AccessSession) and session.staff.role in Staff.CLINICAL_ROLES
