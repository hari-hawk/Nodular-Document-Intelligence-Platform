# Amendment extraction guidance

An amendment modifies an existing contract. The brain should extract
enough to merge it into the parent contract.

Required:
- `agreement_number` — the parent contract this amendment modifies
  (look for "Amendment to MSA-12345" or "Reference: …")
- `effective_date` — when the amendment takes effect
- `parties` — same parties as the parent, ideally

Fields the amendment *might* change — extract only the ones the
amendment touches; leave the rest null:
- `expiration_date` (term extension)
- `term_months`
- `auto_renew` / `auto_renew_notice_days`
- `total_contract_value` / `annual_spend_cap`
- `payment_terms`

Return JSON only.
