import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from staff.models import Staff


class Command(BaseCommand):
    """Idempotent (get_or_create/update_or_create) so it's safe to run on every
    deploy via the build step, on hosts (e.g. Render's free tier) with no shell
    access for one-off commands. Encodes real, user-supplied enrollment data
    (see CLAUDE.md "Enrollment data") — not a synthetic/placeholder account.

    Password is read from STAFF_LOGIN_PASSWORD (set in Render's Environment
    tab, never committed) rather than hardcoded, so it never lands in git
    history.
    """

    help = "Create or update the Dr. Maaji staff login for the deployed demo."

    def handle(self, *args, **options):
        password = os.environ.get('STAFF_LOGIN_PASSWORD')
        if not password:
            raise CommandError(
                'STAFF_LOGIN_PASSWORD is not set. Add it as an environment '
                'variable (Render: Environment tab; local: backend/.env) before running this.'
            )

        User = get_user_model()

        user, created = User.objects.get_or_create(
            username='Maaji',
            defaults={'is_staff': True, 'is_superuser': True},
        )
        user.set_password(password)
        user.is_staff = True
        user.is_superuser = True
        user.save()
        self.stdout.write(f"{'user created' if created else 'user updated'} {user.username}")

        staff, s_created = Staff.objects.update_or_create(
            user=user,
            defaults={
                'staff_id': '282828',
                'full_name': 'Maaji Shettima Bukar',
                'role': Staff.Role.DOCTOR,
                'ward': 'General Male Ward',
                'on_duty': True,
            },
        )
        self.stdout.write(f"{'staff created' if s_created else 'staff updated'} {staff}")
