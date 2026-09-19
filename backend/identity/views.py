from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from patients.models import Patient, PatientCategoryRecord
from staff.permissions import IsAdmin, IsClinicalStaff

from .crypto import decrypt_minutiae, encrypt_minutiae
from .extraction import UnreadableImage, extract_minutiae
from .matching import similarity_score
from .models import FingerprintTemplate
from .serializers import EnrollFingerprintSerializer, IdentifyFingerprintSerializer

# Emergency-summary field lookup: (category, field name) pairs pulled from
# each matched patient's own structured category content -- deliberately a
# MINIMAL summary (CLAUDE.md's own wording), not the full 13-category
# record. See patients/category_fields.py for what each category actually
# stores.
SUMMARY_FIELDS = {
    "blood_type": (3, "blood_type"),
    "drug_allergies": (6, "drug_allergies"),
    "other_allergies": (6, "other_allergies"),
    "current_medications": (5, "current_medications"),
    "current_diagnoses": (4, "current_diagnoses"),
    "next_of_kin": (1, "next_of_kin"),
}


def _emergency_summary(patient):
    records_by_category = {
        r.category: r.content
        for r in PatientCategoryRecord.objects.filter(
            patient=patient, category__in={cat for cat, _ in SUMMARY_FIELDS.values()}
        )
    }
    summary = {}
    for key, (category, field) in SUMMARY_FIELDS.items():
        summary[key] = records_by_category.get(category, {}).get(field, "")
    return summary


class EnrollFingerprintView(APIView):
    """POST /api/identity/enroll/ -- multipart {patient_id, image}. Admin-only
    (matches this app's existing "Admin manages patient data" boundary).
    Extracts real minutiae from the uploaded image (never written to disk --
    see identity.extraction), encrypts them, and stores/replaces this
    patient's FingerprintTemplate. The raw image itself is discarded once
    this request finishes; nothing about it is persisted anywhere."""

    permission_classes = [IsAdmin]

    def post(self, request):
        serializer = EnrollFingerprintSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient = get_object_or_404(Patient, pk=serializer.validated_data["patient_id"])

        image = serializer.validated_data["image"]
        try:
            minutiae = extract_minutiae(image.read())
        except UnreadableImage as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if len(minutiae) < 5:
            return Response(
                {"detail": "Too few minutiae detected in this image -- try a clearer, well-lit scan."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        FingerprintTemplate.objects.update_or_create(
            patient=patient,
            defaults={
                "encrypted_template": encrypt_minutiae(minutiae),
                "enrolled_by_staff_id": request.auth.staff.staff_id,
            },
        )
        return Response({"detail": "Fingerprint enrolled.", "minutiae_count": len(minutiae)})


class IdentifyFingerprintView(APIView):
    """POST /api/identity/identify/ -- multipart {image}, deliberately no
    patient_id (that's the whole point -- this identifies an unknown
    patient). Open to any clinical staff member, matching CLAUDE.md's
    "staff performing emergency or offline lookup" framing -- not gated
    behind a specific role, since any clinical role could be the one
    finding an unconscious/unidentified patient.

    Compares the probe against every enrolled template and returns the
    best match above settings.FINGERPRINT_MATCH_THRESHOLD, or a plain "no
    match" -- an ordinary, expected outcome for an unenrolled patient, not
    an error."""

    permission_classes = [IsClinicalStaff]

    def post(self, request):
        serializer = IdentifyFingerprintSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        image = serializer.validated_data["image"]
        try:
            probe = extract_minutiae(image.read())
        except UnreadableImage as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        best_patient = None
        best_score = 0.0
        for template in FingerprintTemplate.objects.select_related("patient"):
            score = similarity_score(probe, decrypt_minutiae(template.encrypted_template))
            if score > best_score:
                best_score = score
                best_patient = template.patient

        if best_patient is None or best_score < settings.FINGERPRINT_MATCH_THRESHOLD:
            return Response({"matched": False, "score": round(best_score, 2)})

        return Response(
            {
                "matched": True,
                "score": best_score,
                "patient": {
                    "id": best_patient.id,
                    "hospital_number": best_patient.hospital_number,
                    "full_name": best_patient.full_name,
                    "ward": best_patient.ward,
                },
                "summary": _emergency_summary(best_patient),
            }
        )


class OfflineFingerprintBundleView(APIView):
    """GET /api/identity/offline-bundle/ -- Offline Mode's fingerprint gap
    (MedGuard Identity, added 2026-09-17). Identification mode can't know
    which patient it's looking for in advance, so unlike the rest of
    Offline Mode's per-patient cache (built organically as a clinician
    views patients online), fingerprint lookup needs the *whole* enrolled
    roster available on-device before the network ever goes down --
    confirmed with the user via AskUserQuestion rather than assumed.

    Decrypts every FingerprintTemplate server-side (same
    identity.crypto.decrypt_minutiae call IdentifyFingerprintView already
    makes in its matching loop) and returns the plaintext minutiae plus the
    same minimal emergency summary identify already exposes -- the device
    re-encrypts this at rest immediately on receipt (frontend/src/offline/
    fingerprintCache.js), the same protection level refreshOfflineCache
    already gives full patient records today. Open to any clinical staff
    member, matching IdentifyFingerprintView's own permission model."""

    permission_classes = [IsClinicalStaff]

    def get(self, request):
        templates = []
        for template in FingerprintTemplate.objects.select_related("patient"):
            patient = template.patient
            templates.append(
                {
                    "patient": {
                        "id": patient.id,
                        "hospital_number": patient.hospital_number,
                        "full_name": patient.full_name,
                        "ward": patient.ward,
                    },
                    "minutiae": decrypt_minutiae(template.encrypted_template),
                    "summary": _emergency_summary(patient),
                }
            )
        return Response({"templates": templates})
