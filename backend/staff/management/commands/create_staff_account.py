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

    No arguments: creates/updates the original Dr. Maaji demo account (unchanged
    behavior, so the existing no-argument Render build-step invocation keeps working).
    With arguments: creates/updates whichever real staff account the caller specifies
    -- e.g. the bootstrap Admin account, since there's no admin dashboard yet to create
    the very first admin through.
    """

    help = "Create or update a real staff login. With no arguments, the Dr. Maaji demo account."

    def add_arguments(self, parser):
        parser.add_argument('--username', default='Maaji')
        parser.add_argument('--staff-id', default='282828')
        parser.add_argument('--full-name', default='Maaji Shettima Bukar')
        parser.add_argument('--role', default=Staff.Role.DOCTOR, choices=Staff.Role.values)
        parser.add_argument('--ward', default='General Male Ward')
        parser.add_argument('--on-duty', action='store_true', default=True)

    def handle(self, *args, **options):
        password = os.environ.get('STAFF_LOGIN_PASSWORD')
        if not password:
            raise CommandError(
                'STAFF_LOGIN_PASSWORD is not set. Add it as an environment '
                'variable (Render: Environment tab; local: backend/.env) before running this.'
            )

        User = get_user_model()

        user, created = User.objects.get_or_create(
            username=options['username'],
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
                'staff_id': options['staff_id'],
                'full_name': options['full_name'],
                'role': options['role'],
                'ward': options['ward'],
                'on_duty': options['on_duty'],
            },
        )
        self.stdout.write(f"{'staff created' if s_created else 'staff updated'} {staff}")
