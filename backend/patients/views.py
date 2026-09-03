from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from staff.models import Staff, Ward
from staff.permissions import IsAdmin

from .models import Patient, PatientAssignment, PatientCategoryRecord
from .serializers import (
    AssignedPatientSerializer,
    PatientAssignmentCreateSerializer,
    PatientAssignmentSerializer,
    PatientCategoryContentUpdateSerializer,
    PatientCategoryRecordSerializer,
    PatientCreateSerializer,
    PatientSummarySerializer,
    PatientWardUpdateSerializer,
)


class PatientSearchView(APIView):
    """GET /api/patients/?q=...&ward=... -- any authenticated staff (the search step
    has to happen before the system knows what the caller is allowed to see; the
    actual category content is gated separately, in scoring.views.PatientRecordView).
    ward is an exact match against Ward, used by the Admin dashboard's ward-category
    drill-down so results aren't limited by the 50-row search cap below."""

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        ward = request.query_params.get("ward", "").strip()
        patients = Patient.objects.all()
        if q:
            patients = patients.filter(Q(hospital_number__icontains=q) | Q(full_name__icontains=q))
        if ward:
            patients = patients.filter(ward=ward)
        return Response(PatientSummarySerializer(patients[:50], many=True).data)


class PatientSummaryView(APIView):
    """GET /api/patients/summary/ -- real counts for the Admin dashboard's overview
    page and ward-category tiles (not the 50-row search cap)."""

    permission_classes = [IsAdmin]

    def get(self, request):
        by_ward = {ward: 0 for ward, _ in Ward.choices}
        by_ward["unassigned"] = 0
        for row in Patient.objects.values("ward").annotate(count=Count("id")):
            by_ward[row["ward"] or "unassigned"] = row["count"]
        return Response({
            "total": Patient.objects.count(),
            "by_ward": by_ward,
        })


class PatientCreateView(APIView):
    """POST /api/patients/ -- creates the Patient plus its 13 empty
    PatientCategoryRecord rows (empty structure, not fabricated content)."""

    permission_classes = [IsAdmin]

    def post(self, request):
        serializer = PatientCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            patient = serializer.save()
            PatientCategoryRecord.objects.bulk_create(
                PatientCategoryRecord(patient=patient, category=category)
                for category, _ in PatientCategoryRecord.Category.choices
            )

        return Response(PatientSummarySerializer(patient).data, status=status.HTTP_201_CREATED)


class PatientWardUpdateView(APIView):
    """PATCH /api/patients/<id>/ward/"""

    permission_classes = [IsAdmin]

    def patch(self, request, patient_id):
        patient = get_object_or_404(Patient, pk=patient_id)
        serializer = PatientWardUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient.ward = serializer.validated_data["ward"]
        patient.save(update_fields=["ward", "updated_at"])
        return Response(PatientSummarySerializer(patient).data)


class PatientCategoryRecordsView(APIView):
    """GET /api/patients/<id>/records/all/ -- every category's raw content,
    unfiltered by any access decision. Admin-only: this is the editing view, not the
    role-gated clinical read (see scoring.views.PatientRecordView for that)."""

    permission_classes = [IsAdmin]

    def get(self, request, patient_id):
        get_object_or_404(Patient, pk=patient_id)
        records = PatientCategoryRecord.objects.filter(patient_id=patient_id)
        return Response(PatientCategoryRecordSerializer(records, many=True).data)


class PatientCategoryUpdateView(APIView):
    """PATCH /api/patients/<id>/records/<category>/ -- admin edits one category's
    content directly; not subject to the Scoring Engine (that gate is for clinical
    staff reading records, not for admin data entry)."""

    permission_classes = [IsAdmin]

    def patch(self, request, patient_id, category):
        record = get_object_or_404(PatientCategoryRecord, patient_id=patient_id, category=category)
        serializer = PatientCategoryContentUpdateSerializer(data=request.data, context={"category": category})
        serializer.is_valid(raise_exception=True)
        record.content = serializer.validated_data["content"]
        record.save(update_fields=["content", "updated_at"])
        return Response(PatientCategoryRecordSerializer(record).data)


class PatientAssignmentListCreateView(APIView):
    """GET/POST /api/patients/<id>/assignments/ -- current active assignments, or
    create a new one (doctor or nurse)."""

    permission_classes = [IsAdmin]

    def get(self, request, patient_id):
        get_object_or_404(Patient, pk=patient_id)
        assignments = PatientAssignment.objects.filter(patient_id=patient_id, active=True).select_related("staff")
        return Response(PatientAssignmentSerializer(assignments, many=True).data)

    def post(self, request, patient_id):
        patient = get_object_or_404(Patient, pk=patient_id)
        serializer = PatientAssignmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        staff = get_object_or_404(Staff, staff_id=serializer.validated_data["staff_id"])

        assignment, created = PatientAssignment.objects.get_or_create(
            patient=patient,
            staff=staff,
            role_in_assignment=serializer.validated_data["role_in_assignment"],
            active=True,
            defaults={},
        )
        return Response(
            PatientAssignmentSerializer(assignment).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PatientAssignmentDeactivateView(APIView):
    """DELETE /api/patients/<id>/assignments/<assignment_id>/ -- soft-deactivate
    (PatientAssignment rows are never hard-deleted, so assignment history survives)."""

    permission_classes = [IsAdmin]

    def delete(self, request, patient_id, assignment_id):
        assignment = get_object_or_404(
            PatientAssignment, pk=assignment_id, patient_id=patient_id, active=True
        )
        assignment.active = False
        assignment.save(update_fields=["active"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyAssignedPatientsView(APIView):
    """GET /api/patients/assigned-to-me/ -- empty list for roles with no assignment
    concept, rather than an error, so the dashboard can call this unconditionally."""

    def get(self, request):
        staff = request.auth.staff
        assignments = PatientAssignment.objects.filter(staff=staff, active=True).select_related("patient")
        return Response(AssignedPatientSerializer(assignments, many=True).data)


class StaffAssignmentsView(APIView):
    """GET /api/patients/staff/<staff_pk>/assignments/ -- admin-only, that staff
    member's active patient assignments. The reverse lookup of
    PatientAssignmentListCreateView's GET above -- added 2026-09-03, per the user,
    so the Admin dashboard's Staff panel can assign a patient to a staff member
    directly, not just the other way around via the Patient panel."""

    permission_classes = [IsAdmin]

    def get(self, request, staff_pk):
        staff = get_object_or_404(Staff, pk=staff_pk)
        assignments = PatientAssignment.objects.filter(staff=staff, active=True).select_related("patient")
        return Response(AssignedPatientSerializer(assignments, many=True).data)
