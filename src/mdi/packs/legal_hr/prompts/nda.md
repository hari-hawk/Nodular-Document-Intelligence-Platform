# NDA extraction guidance

A non-disclosure / confidentiality agreement.

Required:
- `parties` — for NDAs the roles are `disclosing_party` and `receiving_party`,
  or both labeled the same in a mutual NDA.
- `effective_date`
- `agreement_type` — "Mutual NDA", "Unilateral NDA", etc.
- `confidentiality_term_years` — typically 2, 3, 5, or 7

`expiration_date` may not exist; many NDAs run "in perpetuity" relative
to the confidentiality term. Leave null in that case.

`governing_law` and `clauses_detected` apply as in `contract.md`.

Financial fields (`total_contract_value`, `currency`, etc.) are usually null.

Return JSON only.
