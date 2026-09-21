"""The MINIMAL emergency summary of a patient -- blood type, allergies,
current medication, current diagnoses, next of kin -- assembled from that
patient's own structured category content.

CLAUDE.md's Bonus Layer section names exactly these fields ("a minimal
summary (blood type, allergies, current meds, major diagnoses, emergency
contact)"), deliberately NOT the full 13-category record.

Lived in identity/views.py until 2026-09-21, when a second consumer
appeared: Offline Mode's ward roster (patients.views.WardEmergencySummaryView)
needs the identical summary for every patient on a clinician's own ward, not
just the ones with an enrolled fingerprint. Nothing here was ever
fingerprint-specific -- it only reads PatientCategoryRecord -- so it moved
down to `patients`, which sits before `identity` in this project's one-way
app dependency order, and both callers import it from here.
"""

from .models import PatientCategoryRecord

# (category number, field name) per summary key. See
# patients/category_fields.py for what each category actually stores.
SUMMARY_FIELDS = {
    "blood_type": (3, "blood_type"),
    "drug_allergies": (6, "drug_allergies"),
    "other_allergies": (6, "other_allergies"),
    "current_medications": (5, "current_medications"),
    "current_diagnoses": (4, "current_diagnoses"),
    "next_of_kin": (1, "next_of_kin"),
}

SUMMARY_CATEGORIES = {category for category, _ in SUMMARY_FIELDS.values()}


def emergency_summary(patient):
    """One patient's summary. Every key is always present -- a field that
    hasn't been filled in yet comes back as an empty string rather than
    being omitted, so the frontend renders a consistent card either way."""
    records_by_category = {
        r.category: r.content
        for r in PatientCategoryRecord.objects.filter(
            patient=patient, category__in=SUMMARY_CATEGORIES
        )
    }
    return {
        key: (records_by_category.get(category) or {}).get(field, "")
        for key, (category, field) in SUMMARY_FIELDS.items()
    }


def emergency_summaries_for(patients):
    """The same thing for many patients in ONE query instead of one query
    each -- the ward roster endpoint builds a summary for every patient on a
    ward, so the per-patient version would be N queries deep.

    Returns {patient_id: summary}, with an all-empty summary for a patient
    that has no category rows at all.
    """
    patient_ids = [p.id for p in patients]
    content_by_patient = {pid: {} for pid in patient_ids}
    rows = PatientCategoryRecord.objects.filter(
        patient_id__in=patient_ids, category__in=SUMMARY_CATEGORIES
    ).values_list("patient_id", "category", "content")
    for patient_id, category, content in rows:
        content_by_patient[patient_id][category] = content

    return {
        pid: {
            key: (content_by_patient[pid].get(category) or {}).get(field, "")
            for key, (category, field) in SUMMARY_FIELDS.items()
        }
        for pid in patient_ids
    }
