You are extracting structured fields from an INSURANCE POLICY document
(declarations page, renewal notice, or endorsement).

Return ONLY a JSON object — no prose, no markdown fences. Every field
below is optional unless marked REQUIRED; emit `null` (not the string
"null", not absent) when the document doesn't state a value. Do NOT
hallucinate.

CANONICAL FIELD NAMES (use these exact keys):

  vendor              REQUIRED. The insurance carrier name as printed
                      (e.g., "State Farm", "Allstate Insurance", "Progressive Group").
                      Do NOT include the word "Insurance" twice. Strip trailing
                      "Corporation" / "Inc." only if it doesn't appear on the doc.

  customer            The named insured / policyholder as printed.
                      Use the primary name only — additional insureds go in `notes`.

  document_number     The policy identifier exactly as printed. Preserve
                      hyphens and prefixes ("AP-44719-002", not "44719").

  policy_type         REQUIRED. EXACTLY one lowercase token from this set:
                        auto | home | life | commercial_property
                        | commercial_liability | umbrella | health
                      INFER from the document body if not stated verbatim:
                        - "Personal Auto" / vehicle / VIN listed     -> auto
                        - "Homeowners" / "HO-3" / "Dwelling" coverage -> home
                        - "Term Life" / face amount / beneficiary    -> life
                        - "Commercial Property" / "BOP"               -> commercial_property
                        - "CGL" / "General Liability"                 -> commercial_liability
                        - "Umbrella" coverage                         -> umbrella
                      Never emit `null` for this field — infer from coverages.

  document_date       Policy effective date, ISO-8601 YYYY-MM-DD.

  due_date            Policy expiration date, ISO-8601 YYYY-MM-DD.

  currency            "USD" unless the document clearly states another.

  total               The premium amount as a number (no $ or commas).
                      If the document shows a 6-month or quarterly premium,
                      extract that value (don't annualise) — note the
                      frequency in `notes`.

  coverage_amount     The PRIMARY headline coverage limit (number, no $/commas).
                      Pack the most-meaningful single limit per policy type:
                        - auto:  bodily-injury per-person limit (first of split limits)
                        - home:  Coverage A — Dwelling
                        - life:  face amount
                        - commercial_property: building limit
                        - commercial_liability: each-occurrence limit
                      Other coverages on the same policy go in `notes`.

  deductible          The headline deductible (number, no $/commas).

  insured_property    Free-text description of the insured property:
                      vehicle make/model/VIN for auto, address for home,
                      insured's name for life. ONE row only — additional
                      vehicles/properties go in `notes`.

  notes               Free-text. Useful for: payment frequency, additional
                      insureds, riders, second vehicles on auto policies,
                      claims-made vs occurrence wording on liability, etc.

Match the values EXACTLY as printed — don't paraphrase the policyholder
name or normalize the case of the carrier. Money is a number, dates
are ISO-8601, currency is a 3-letter ISO-4217 code.
