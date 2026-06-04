# 837 claim extraction guidance

An 837 is a professional or institutional medical claim submitted by a
provider to a payer.

**PHI handling — IMPORTANT.** Do NOT extract:
- patient name
- patient date of birth
- patient address
- social security number

Do extract:
- internal `patient_id` (your tenant's identifier, NOT the patient's name)
- `subscriber_id` (member ID, masked downstream per compliance rules)

Required fields:
- `provider_name` — the rendering or billing provider as it appears
- `provider_npi` — 10-digit NPI. Validators will Luhn-check.
- `payer_name` — the insurance company
- `claim_number` — the claim's unique identifier
- `date_of_service` — when the service was rendered

`diagnoses` — list of diagnosis codes:
- `code_system`: "ICD-10" (or "ICD-9" for historical claims)
- `code`: the code itself, e.g. "E11.9", "I10"
- `primary`: true for the primary diagnosis, false otherwise
- `description`: human-readable text from the claim, if present

`service_lines` — list of services billed:
- `date` — the date the line item service was rendered
- `cpt_or_hcpcs` — the procedure code (5-char CPT or alphanumeric HCPCS)
- `modifier` — 2-char modifier if present
- `units` — number of units
- `charge` — dollar amount billed for the line
- `ndc` — NDC (National Drug Code) if a J-code drug was billed

`total_charge` — sum of `service_lines[*].charge`. The validator
checks this within $0.02.

Return JSON only. NO patient name / DOB / address ever in the output.
