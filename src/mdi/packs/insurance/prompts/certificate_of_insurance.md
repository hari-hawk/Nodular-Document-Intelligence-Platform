You are extracting structured fields from a CERTIFICATE OF INSURANCE
(typically ACORD-25 or ACORD-27 form).

Return ONLY a JSON object — no prose, no markdown fences. Use `null`
for missing values. Do NOT hallucinate.

CANONICAL FIELD NAMES:

  vendor              REQUIRED. The insurance carrier issuing the COI.
                      A COI may list multiple carriers (one per
                      coverage line); use the PRIMARY carrier on the
                      first listed coverage. Other carriers go in `notes`.

  customer            The certificate holder name (the party the COI
                      is issued TO — not the insured party).

  document_number     The COI's own identifier if printed. Many COIs
                      don't have one; emit `null` in that case.

  policy_number       REQUIRED. The FIRST listed policy's number on the
                      COI. ACORD certificates list multiple policies as
                      separate rows; pick the topmost one's policy number
                      and put the remaining policies in `notes`. NEVER
                      leave this `null` if any policy is shown.

  policy_type         REQUIRED. EXACTLY one lowercase token from:
                        commercial_liability | auto | umbrella |
                        commercial_property | health | home | life
                      Most COIs lead with Commercial General Liability
                      (CGL) — that maps to commercial_liability.

  document_date       The COI issue date in ISO-8601 YYYY-MM-DD.

  due_date            The earliest expiration date among the listed
                      policies. A COI lapses when any policy on it lapses.

  currency            "USD" unless otherwise stated.

  total               Usually `null` — a COI doesn't have a single
                      amount. Emit `null` for COIs without an aggregate
                      premium summary.

  coverage_amount     The HIGHEST listed limit across all coverages.
                      For commercial liability that's typically the
                      general aggregate limit.

  deductible          The first listed deductible (often null on COIs).

  insured_property    The named insured's description. Insurance address
                      OR the operations description if printed.

  notes               Free-text. Use for: additional carriers, additional
                      insureds, multiple policies with their numbers and
                      coverages, special endorsements / waivers.
