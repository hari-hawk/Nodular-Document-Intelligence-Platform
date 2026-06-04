# Prior authorization extraction guidance

A prior auth request is what a provider submits before delivering a
service that requires payer approval.

PHI rules from `claim_837.md` apply.

Required:
- `provider_name`, `provider_npi`
- `payer_name`, `payer_id`
- `patient_id` (internal), `subscriber_id`

`diagnoses` — supporting clinical justification (same shape).
`service_lines` — requested procedures (same shape; `paid_amount` is null).
`date_of_service` — the planned service date.

`claim_number` is null on prior auths (no claim has been billed yet).
Capture the prior-auth-specific identifier in `claim_number` if the
document carries one; otherwise leave null.

Return JSON only.
