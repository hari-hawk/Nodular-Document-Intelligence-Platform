# Offer letter extraction guidance

A pre-employment offer — typically lighter than a full employment
agreement.

Required:
- `parties` — `employer` and `employee` (offeree)
- `position_title`
- `start_date`
- `base_salary`
- `currency`

Often present:
- `expiration_date` — offer expiry (when the offer must be accepted)

`clauses_detected` — offer letters reference but rarely include
full clause text; mark `present=true` for any clause the letter
*references* (e.g. "subject to our standard employment agreement
which includes non-compete and IP assignment").

Return JSON only.
