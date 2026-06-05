You are extracting structured fields from an INSURANCE ADJUSTER REPORT
(damage estimate, loss assessment, or property inspection report).

Return ONLY a JSON object — no prose, no markdown fences. Use `null`
for missing values.

CANONICAL FIELD NAMES:

  vendor              REQUIRED. The carrier OR the adjusting firm
                      conducting the assessment (different from claim
                      forms — here the adjuster's firm is usually the
                      "vendor" since they issued the report).

  customer            The claimant / property owner being assessed.

  document_number     The adjuster report identifier as printed.

  policy_number       REQUIRED if cross-referenced (almost always is).
                      The underlying policy number being adjusted
                      against. Keep this separate from document_number
                      (the adjuster report's own id).

  claim_number        The associated claim id, if shown.

  policy_type         REQUIRED. EXACTLY one lowercase token from:
                        home | commercial_property | auto | life |
                        commercial_liability | umbrella | health
                      INFER from the insured property:
                        - vehicle / VIN  -> auto
                        - dwelling / property address -> home
                        - building / commercial premises -> commercial_property
                      Never `null`.

  total               REQUIRED. The NET PAYABLE amount (gross loss minus
                      deductible) as a number, no $/commas. Adjuster
                      reports usually print both ESTIMATED LOSS and NET
                      PAYABLE — we want the NET PAYABLE because that's
                      what gets paid out. Put the gross loss in `notes`.

  document_date       Date of inspection / assessment in ISO-8601.

  total               The TOTAL estimated loss / repair cost as a
                      number (no $/commas).

  deductible          The deductible being subtracted from the
                      payout, if shown.

  insured_property    The address / vehicle / item assessed.

  notes               Free-text. Useful for: scope of damage, cause of
                      loss (fire / theft / collision), depreciation
                      treatment, ACV vs RCV split, adjuster name.
