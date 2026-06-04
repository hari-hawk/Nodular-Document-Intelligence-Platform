# Lab report extraction guidance

A laboratory diagnostic report — pathology, hematology, microbiology, etc.

PHI rules apply. Capture:
- `provider_name` — ordering provider
- `provider_npi` — ordering provider's NPI
- `patient_id` — internal identifier (NOT name/DOB)
- `date_of_service` — specimen collection date

`diagnoses` — preliminary or final ICD-10 codes when the report contains them.

`service_lines` — one per ordered test; `cpt_or_hcpcs` is the lab CPT,
`units` is typically 1.

This is the lightest schema in the pack — most lab reports won't fill
in financials. Leave `total_charge` etc. null.

Return JSON only.
