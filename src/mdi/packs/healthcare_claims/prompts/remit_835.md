# 835 remittance / EOB extraction guidance

An 835 (also known as an ERA or paper EOB) is the payer's response
to one or more 837 claims — what was paid, what was denied, and why.

Same PHI exclusion list as `claim_837.md`.

Required:
- `provider_name`, `provider_npi`, `payer_name`, `payer_id`
- `claim_number` — the claim this remit pays. Multiple remits may
  reference the same claim if it spans multiple checks.

Per-service-line fields:
- `cpt_or_hcpcs`, `modifier`, `units`, `charge` — as on the claim
- `paid_amount` — what the payer actually paid for this line

`total_charge` — sum of `service_lines[*].charge`
`total_paid` — sum of `service_lines[*].paid_amount`

`adjustment_codes` — list of CARC (Claim Adjustment Reason) and
RARC (Remittance Advice Remark) codes explaining any denial /
adjustment. Each entry: `{code, type: CARC|RARC, amount, reason}`.

Return JSON only.
