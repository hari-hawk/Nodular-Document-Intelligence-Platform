# Customer Service Record (CSR) extraction guidance

A CSR is the carrier's authoritative *inventory* of services on an
account. Unlike an invoice (which says what was charged), a CSR says
what is provisioned. They reconcile.

Required:
- `carrier`, `customer`, `account_number` — same conventions as the invoice.

Service lines (`service_lines`) — one row per provisioned service.
For CSRs the unit_price/mrc_total fields may be empty; populate
`service_type` + `quantity` reliably.

`phone_numbers` — list every DID / DDI on the account. E.164.

`contract_reference` — if cited, the MSA the inventory is provisioned under.

CSRs typically lack subtotal/tax/total. Leave those null with confidence 0.

Return JSON only.
