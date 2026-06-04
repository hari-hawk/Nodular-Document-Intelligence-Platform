# Contract extraction guidance

A commercial contract — MSA, SOW, services or license agreement.

Required:
- `parties` — list every party with their role:
  - `name` — legal entity name as printed
  - `role` — one of buyer / seller / service_provider / customer /
    licensor / licensee
  - `jurisdiction` — state/country of incorporation if cited

- `agreement_number` — the contract identifier
- `agreement_type` — free text from the title
- `effective_date` — when obligations start
- `expiration_date` — when the initial term ends
- `term_months` — initial term in months (if "Initial Term: 24 months" is printed)

**Auto-renew detection** — critical:
- `auto_renew` (boolean) — true iff the contract auto-renews unless terminated
- `auto_renew_notice_days` — days of notice required to opt out
  (e.g. "auto-renews for successive 12-month terms unless either party
  gives 90 days written notice" → auto_renew=true, notice=90)

`total_contract_value` — committed value over the initial term.
`annual_spend_cap` — if a separate cap is named (different from total).
`currency` — ISO 4217.
`payment_terms` — "Net 30", "Net 60", etc.
`governing_law` — state/country.
`confidentiality_term_years` — if a confidentiality clause has its own term.

`clauses_detected` — for each clause type in the enumeration, set
`present` to true/false. Use the LLM's judgement; clauses are
typically named directly or describable as the relevant section heading.

Return JSON only.
