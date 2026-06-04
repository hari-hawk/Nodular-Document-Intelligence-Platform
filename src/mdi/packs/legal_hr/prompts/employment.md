# Employment agreement extraction guidance

A formal employment contract.

Required:
- `parties` — roles are `employer` and `employee`
- `position_title`
- `start_date`
- `base_salary` — annual base
- `currency`
- `effective_date` — typically same as start_date but sometimes earlier
  (signed before start)

Useful when present:
- `expiration_date` — for fixed-term contracts; otherwise null (at-will)
- `term_months` — only meaningful for fixed-term
- `auto_renew`, `auto_renew_notice_days` — fixed-term rolls

`clauses_detected` matters here too:
- `non_compete`, `non_solicit`, `ip_assignment`, `confidentiality` —
  HR teams care about these specifically

Return JSON only.
