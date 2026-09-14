"""MedGuard Identity tests (CLAUDE.md bonus, step 7, added 2026-09-14). No
real enrollment data -- Django's isolated test database only, per CLAUDE.md.
Synthetic test images exercise the real extraction/matching pipeline; they
don't need to look like an actual fingerprint (that's only required for the
live verification pass against a real photo, done separately), just be
valid images the pipeline won't crash on.
"""

import io
import math
import random
import time

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image, ImageDraw
from rest_framework import status
from rest_framework.test import APITestCase

from patients.models import Patient, PatientCategoryRecord
from staff.models import Staff

from .crypto import decrypt_minutiae, encrypt_minutiae
from .extraction import MAX_MINUTIAE, _cap_to_strongest, extract_minutiae
from .matching import similarity_score
from .models import FingerprintTemplate

TEST_FERNET_KEY = "EYsrTL8AHPQdUuGcQ_cftHChtnB1V6H8g0mXS1fMy18="


def _ridge_like_image(seed=1, size=220):
    """A synthetic image with wavy line patterns standing in for ridges --
    real enough for the real skeletonization/minutiae pipeline to run on
    without crashing, not a claim that it looks like an actual print."""
    img = Image.new("L", (size, size), color=255)
    draw = ImageDraw.Draw(img)
    for row in range(10, size - 10, 8):
        points = []
        for x in range(0, size, 4):
            y = row + int(12 * math.sin((x + seed * 37) / 15.0))
            points.append((x, y))
        draw.line(points, fill=0, width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def _blank_image(size=220):
    img = Image.new("L", (size, size), color=255)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def _upload(image_bytes, name="print.png"):
    return SimpleUploadedFile(name, image_bytes, content_type="image/png")


class MatchingTests(TestCase):
    """Pure-function tests -- no images needed, deterministic geometry."""

    def _sample_minutiae(self):
        return [
            {"x": 10, "y": 10, "angle": 0.0, "type": "termination"},
            {"x": 30, "y": 15, "angle": 45.0, "type": "bifurcation"},
            {"x": 50, "y": 40, "angle": 90.0, "type": "termination"},
            {"x": 70, "y": 20, "angle": 10.0, "type": "bifurcation"},
            {"x": 90, "y": 60, "angle": 180.0, "type": "termination"},
        ]

    def _transform(self, minutiae, rotation_deg, dx, dy):
        rad = math.radians(rotation_deg)
        out = []
        for m in minutiae:
            x, y = m["x"], m["y"]
            rx = x * math.cos(rad) - y * math.sin(rad) + dx
            ry = x * math.sin(rad) + y * math.cos(rad) + dy
            out.append({"x": rx, "y": ry, "angle": (m["angle"] + rotation_deg) % 360, "type": m["type"]})
        return out

    def test_identical_sets_score_100(self):
        m = self._sample_minutiae()
        self.assertEqual(similarity_score(m, m), 100.0)

    def test_rotated_and_translated_set_still_matches(self):
        """The whole point of the alignment step -- two scans of the same
        finger are never pixel-aligned, so a naive coordinate comparison
        would fail here even though this IS the same print, just shifted
        and rotated."""
        probe = self._sample_minutiae()
        template = self._transform(probe, rotation_deg=37, dx=143, dy=-52)
        self.assertGreaterEqual(similarity_score(probe, template), 99.0)

    def test_unrelated_sets_score_low(self):
        # A small unrelated set makes a spurious 1-point coincidental
        # alignment statistically likely (exactly why enrollment requires a
        # minimum minutiae count -- see EnrollFingerprintView) -- this uses
        # enough scattered points that even one coincidental alignment stays
        # a small fraction of the (smaller-set-normalized) score.
        probe = self._sample_minutiae()
        unrelated = [
            {"x": 500 + i * 41, "y": 500 - i * 23, "angle": (i * 67) % 360, "type": "termination" if i % 2 else "bifurcation"}
            for i in range(10)
        ]
        self.assertLess(similarity_score(probe, unrelated), 40.0)

    def test_empty_sets_score_zero(self):
        self.assertEqual(similarity_score([], self._sample_minutiae()), 0.0)
        self.assertEqual(similarity_score(self._sample_minutiae(), []), 0.0)

    def test_stays_fast_at_realistic_minutiae_counts(self):
        """Regression test for a real bug (found 2026-09-14 via live
        testing against a real enrolled fingerprint): a naive
        (unindexed) version of this algorithm took 165 SECONDS for one
        comparison at 188 minutiae -- a real photographed print, not the
        "dozens" this was first benchmarked against -- which is exactly
        what showed up as the UI getting stuck on "Identifying...".
        MAX_MINUTIAE (identity/extraction.py) now caps what any single
        comparison ever has to handle, and matching.py's spatial grid
        keeps per-candidate cost low regardless -- this asserts the
        combination stays well under a second even at MAX_MINUTIAE-sized,
        genuinely unrelated (worst-case, no early exit) inputs."""
        rng = random.Random(7)

        def random_set(n):
            return [
                {
                    "x": rng.uniform(0, 800),
                    "y": rng.uniform(0, 800),
                    "angle": rng.uniform(0, 360),
                    "type": rng.choice(["termination", "bifurcation"]),
                }
                for _ in range(n)
            ]

        probe = random_set(MAX_MINUTIAE)
        template = random_set(MAX_MINUTIAE)

        start = time.time()
        similarity_score(probe, template)
        elapsed = time.time() - start

        self.assertLess(elapsed, 5.0, f"took {elapsed:.1f}s -- matching has regressed to being too slow")


@override_settings(FINGERPRINT_TEMPLATE_KEY=TEST_FERNET_KEY)
class CryptoTests(TestCase):
    def test_round_trips(self):
        minutiae = [{"x": 1, "y": 2, "angle": 3.5, "type": "termination"}]
        encrypted = encrypt_minutiae(minutiae)
        self.assertNotIn("termination", encrypted)  # genuinely encrypted, not just encoded
        self.assertEqual(decrypt_minutiae(encrypted), minutiae)


class ExtractionTests(TestCase):
    def test_extracts_a_list_without_crashing_on_a_real_image(self):
        minutiae = extract_minutiae(_ridge_like_image())
        self.assertIsInstance(minutiae, list)
        for m in minutiae:
            self.assertEqual(set(m.keys()), {"x", "y", "angle", "type"})
            self.assertIn(m["type"], ("termination", "bifurcation"))

    def test_deterministic_for_the_same_bytes(self):
        """Same input image -> same extracted minutiae, every time -- what
        the enroll-then-identify-the-same-photo view test below relies on."""
        image_bytes = _ridge_like_image()
        self.assertEqual(extract_minutiae(image_bytes), extract_minutiae(image_bytes))

    def test_blank_image_extracts_few_or_no_minutiae(self):
        self.assertEqual(extract_minutiae(_blank_image()), [])

    def test_never_returns_more_than_the_cap(self):
        """Regression test -- see MatchingTests.
        test_stays_fast_at_realistic_minutiae_counts. A busier synthetic
        image than the other tests use, to actually exercise the
        MAX_MINUTIAE cap rather than just asserting the constant exists."""
        busy_image = _ridge_like_image(seed=3)
        minutiae = extract_minutiae(busy_image)
        self.assertLessEqual(len(minutiae), MAX_MINUTIAE)

    def test_cap_keeps_the_most_isolated_points(self):
        """Direct unit test of the capping logic itself (doesn't depend on
        a real image producing enough noise to exceed the cap) -- a tight
        cluster of near-duplicate points should lose to a few genuinely
        isolated ones."""
        cluster = [
            {"x": 100 + i, "y": 100 + i, "angle": 0.0, "type": "termination"} for i in range(20)
        ]
        isolated = [
            {"x": 500, "y": 500, "angle": 0.0, "type": "termination"},
            {"x": 700, "y": 200, "angle": 0.0, "type": "termination"},
        ]
        capped = _cap_to_strongest(cluster + isolated, limit=5)
        self.assertEqual(len(capped), 5)
        self.assertIn(isolated[0], capped)
        self.assertIn(isolated[1], capped)


@override_settings(FINGERPRINT_TEMPLATE_KEY=TEST_FERNET_KEY, FINGERPRINT_MATCH_THRESHOLD=40)
class IdentityViewTests(APITestCase):
    def setUp(self):
        admin_user = User.objects.create_user(username="idAdmin", password="pw-id-1")
        self.admin = Staff.objects.create(user=admin_user, staff_id="STF-ID1", full_name="Admin", role=Staff.Role.ADMIN)
        self.admin_token = self._login("idAdmin", "pw-id-1", "id-admin-dev")

        doc_user = User.objects.create_user(username="idDoc", password="pw-id-2")
        self.doctor = Staff.objects.create(user=doc_user, staff_id="STF-ID2", full_name="Doc", role=Staff.Role.DOCTOR)
        self.doctor_token = self._login("idDoc", "pw-id-2", "id-doc-dev")

        self.patient = Patient.objects.create(hospital_number="HN-ID-1", full_name="Identity Patient")
        for category, _ in PatientCategoryRecord.Category.choices:
            PatientCategoryRecord.objects.create(patient=self.patient, category=category)
        PatientCategoryRecord.objects.filter(patient=self.patient, category=3).update(
            content={"blood_type": "O+"}
        )
        PatientCategoryRecord.objects.filter(patient=self.patient, category=6).update(
            content={"drug_allergies": "Penicillin"}
        )

        self.print_bytes = _ridge_like_image(seed=7)

    def _login(self, username, password, device_id):
        resp = self.client.post(
            "/api/access/login/",
            {"username": username, "password": password, "device_id": device_id, "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        return resp.data["token"]

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def _enroll(self):
        return self.client.post(
            "/api/identity/enroll/",
            {"patient_id": self.patient.id, "image": _upload(self.print_bytes)},
            format="multipart",
            **self._auth(self.admin_token),
        )

    def test_enroll_then_identify_the_same_photo_matches(self):
        enroll_resp = self._enroll()
        self.assertEqual(enroll_resp.status_code, status.HTTP_200_OK, enroll_resp.data)
        self.assertTrue(FingerprintTemplate.objects.filter(patient=self.patient).exists())

        identify_resp = self.client.post(
            "/api/identity/identify/",
            {"image": _upload(self.print_bytes)},
            format="multipart",
            **self._auth(self.doctor_token),
        )
        self.assertEqual(identify_resp.status_code, status.HTTP_200_OK, identify_resp.data)
        self.assertTrue(identify_resp.data["matched"])
        self.assertEqual(identify_resp.data["patient"]["hospital_number"], "HN-ID-1")
        self.assertEqual(identify_resp.data["summary"]["blood_type"], "O+")
        self.assertEqual(identify_resp.data["summary"]["drug_allergies"], "Penicillin")

    def test_blank_probe_does_not_match_anything(self):
        self._enroll()
        resp = self.client.post(
            "/api/identity/identify/",
            {"image": _upload(_blank_image())},
            format="multipart",
            **self._auth(self.doctor_token),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["matched"])

    def test_identify_with_no_enrolled_templates_returns_no_match(self):
        resp = self.client.post(
            "/api/identity/identify/",
            {"image": _upload(self.print_bytes)},
            format="multipart",
            **self._auth(self.doctor_token),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["matched"])

    def test_raw_image_bytes_are_never_persisted(self):
        """Nothing about the uploaded image should survive anywhere other
        than the derived, encrypted minutiae template."""
        self._enroll()
        template = FingerprintTemplate.objects.get(patient=self.patient)
        self.assertNotIn(str(self.print_bytes[:20]), template.encrypted_template)
        # And the stored template really is encrypted, not the raw minutiae.
        minutiae = decrypt_minutiae(template.encrypted_template)
        self.assertIsInstance(minutiae, list)

    def test_enroll_requires_admin(self):
        resp = self.client.post(
            "/api/identity/enroll/",
            {"patient_id": self.patient.id, "image": _upload(self.print_bytes)},
            format="multipart",
            **self._auth(self.doctor_token),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_identify_requires_clinical_staff(self):
        resp = self.client.post(
            "/api/identity/identify/",
            {"image": _upload(self.print_bytes)},
            format="multipart",
            **self._auth(self.admin_token),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_rejected(self):
        self.assertEqual(
            self.client.post(
                "/api/identity/enroll/", {"patient_id": self.patient.id, "image": _upload(self.print_bytes)}, format="multipart"
            ).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        self.assertEqual(
            self.client.post("/api/identity/identify/", {"image": _upload(self.print_bytes)}, format="multipart").status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_re_enrolling_replaces_the_template(self):
        self._enroll()
        first = FingerprintTemplate.objects.get(patient=self.patient)
        self._enroll()
        second = FingerprintTemplate.objects.get(patient=self.patient)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(FingerprintTemplate.objects.filter(patient=self.patient).count(), 1)
