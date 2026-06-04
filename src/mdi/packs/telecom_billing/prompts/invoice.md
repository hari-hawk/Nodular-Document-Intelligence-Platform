# Telecom invoice extraction guidance

A carrier invoice (AT&T, Verizon, T-Mobile, Lumen, CenturyLink, others).

Required:
- `carrier` — the issuing carrier as it appears on the header / letterhead.
- `customer` — the billed party.
- `account_number` — the carrier's account number. **Preserve leading zeros.**
  Common format: 10 or 13 digits; some carriers prefix with letters.

Period:
- `service_period_start`, `service_period_end` — the billing window.
  Look for phrases like "Service period:", "Billing period:", or
  "Period covered:". ISO 8601 (`YYYY-MM-DD`).
- `document_date` — invoice issue date.
- `due_date` — payment deadline.

Service lines (`service_lines`) — one row per recurring service:
- `service_type`: one of DIA, MPLS, SDWAN, POTS, SIP, HostedVoIP,
  Broadband, BackupCircuit, Other. Normalise common variants:
  "Dedicated Internet Access" → DIA, "SIP Trunk - 25" → SIP, etc.
- `quantity`, `unit_price`, `mrc_total` — numerics with two decimals.

`phone_numbers` — collect any numbers listed in the document into a
flat list. **Emit in E.164** (e.g. `+1 212-555-0101` → `+12125550101`).
If country is ambiguous, prefer the carrier's home country (US for AT&T,
Verizon; UK for BT; etc.).

`contract_reference` — the MSA / SOW number cited on the invoice
("Per MSA-12345", "Contract Reference: …").

Totals:
- `subtotal` (pre-tax)
- `tax` (federal + state + surcharges combined as a single number)
- `total` — must equal subtotal + tax within $0.02.
- `currency` — ISO 4217.

Return JSON only.
