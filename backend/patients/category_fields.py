"""Structured field definitions for each of CLAUDE.md's 13 patient record
categories (added 2026-09-03, per the user -- reverses PatientCategoryRecord's
original "deliberately generic notes field" design; see models.py's updated
docstring). Single source of truth: PatientCategoryRecordSerializer exposes
this per-category so the frontend renders forms purely from what the backend
sends, and PatientCategoryContentUpdateSerializer validates against it, so
there is no schema duplicated in JS.

`type` is one of "text", "textarea", "date", "number", "select" (with an
"options" list). `full_name` is skipped everywhere -- Patient.full_name
already covers it.
"""

CATEGORY_FIELDS = {
    1: [  # Identity
        {"name": "date_of_birth", "label": "Date of birth", "type": "date"},
        {"name": "sex", "label": "Sex", "type": "select", "options": ["Male", "Female"]},
        {"name": "address", "label": "Address", "type": "text"},
        {"name": "phone", "label": "Phone number", "type": "text"},
        {"name": "next_of_kin", "label": "Next of kin", "type": "text"},
        {"name": "marital_status", "label": "Marital status", "type": "text"},
        {"name": "occupation", "label": "Occupation", "type": "text"},
    ],
    2: [  # Administrative/Billing
        {"name": "folder_number", "label": "Folder number", "type": "text"},
        {"name": "insurance_nhis", "label": "Insurance / NHIS", "type": "text"},
        {"name": "billing_payment_history", "label": "Billing / payment history", "type": "textarea"},
        {"name": "admission_date", "label": "Admission date", "type": "date"},
        {"name": "discharge_date", "label": "Discharge date", "type": "date"},
    ],
    3: [  # Vital Signs & Routine Observations
        {"name": "height_cm", "label": "Height (cm)", "type": "number"},
        {"name": "weight_kg", "label": "Weight (kg)", "type": "number"},
        {"name": "blood_pressure", "label": "Blood pressure", "type": "text"},
        {"name": "temperature_c", "label": "Temperature (°C)", "type": "number"},
        {"name": "pulse_bpm", "label": "Pulse (bpm)", "type": "number"},
    ],
    4: [  # Diagnosis & Medical History
        {"name": "current_diagnoses", "label": "Current diagnoses", "type": "textarea"},
        {"name": "past_diagnoses", "label": "Past diagnoses", "type": "textarea"},
        {"name": "chronic_conditions", "label": "Chronic conditions", "type": "textarea"},
    ],
    5: [  # Medication & Prescriptions
        {"name": "current_medications", "label": "Current medications", "type": "textarea"},
        {"name": "prescription_history", "label": "Prescription history", "type": "textarea"},
        {"name": "dosages", "label": "Dosages", "type": "textarea"},
    ],
    6: [  # Allergies
        {"name": "drug_allergies", "label": "Drug allergies", "type": "textarea"},
        {"name": "other_allergies", "label": "Other allergies", "type": "textarea"},
    ],
    7: [  # General Lab Results
        {"name": "routine_bloodwork", "label": "Routine bloodwork", "type": "textarea"},
        {"name": "urinalysis", "label": "Urinalysis", "type": "textarea"},
        {"name": "standard_panels", "label": "Standard panels", "type": "textarea"},
    ],
    8: [  # Highly Sensitive Test Results
        {"name": "hiv_status", "label": "HIV status", "type": "text"},
        {"name": "genotype", "label": "Genotype", "type": "text"},
        {"name": "sti_results", "label": "STI results", "type": "textarea"},
        {"name": "pregnancy_status", "label": "Pregnancy status", "type": "text"},
        {"name": "genetic_testing", "label": "Genetic testing", "type": "textarea"},
    ],
    9: [  # Mental Health Records
        {"name": "psychiatric_history", "label": "Psychiatric history", "type": "textarea"},
        {"name": "therapy_counseling_notes", "label": "Therapy / counseling notes", "type": "textarea"},
    ],
    10: [  # Reproductive Health Records
        {"name": "pregnancy_obstetric_history", "label": "Pregnancy / obstetric history", "type": "textarea"},
        {"name": "family_planning", "label": "Family planning", "type": "textarea"},
    ],
    11: [  # Surgical/Procedure History
        {"name": "operations_performed", "label": "Operations performed", "type": "textarea"},
        {"name": "procedure_notes", "label": "Procedure notes", "type": "textarea"},
    ],
    12: [  # Nursing & Care Notes
        {"name": "nursing_observations", "label": "Nursing observations", "type": "textarea"},
        {"name": "care_plan", "label": "Care plan", "type": "textarea"},
    ],
    13: [  # Imaging/Radiology
        {"name": "xrays", "label": "X-rays", "type": "textarea"},
        {"name": "scans", "label": "Scans", "type": "textarea"},
        {"name": "imaging_reports", "label": "Imaging reports", "type": "textarea"},
    ],
}
