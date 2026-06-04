# Telecom MSA / SOW extraction guidance

A telecom contract — Master Service Agreement, Statement of Work, or
amendment.

Required:
- `carrier` — provider party.
- `customer` — purchaser party.
- `contract_reference` — the MSA / SOW number printed on the document.
- `document_date` — effective date.
- `service_period_start` and `service_period_end` — the contracted term.
- `total` — total contracted value (over the term, not per-month).

Service commitments (`service_lines`) — what the contract obligates
the carrier to provide. Per line:
- `service_type` (DIA/MPLS/SIP/...)
- `quantity` — committed count
- `unit_price` — committed MRC per unit
- `mrc_total` — committed monthly recurring charge

`phone_numbers` are typically NOT in contracts; leave null.

Return JSON only.
