# Cloud invoice extraction guidance

A cloud provider invoice (AWS, Azure, GCP, Oracle Cloud).

`provider` — detect from header signals: "Amazon Web Services" → AWS,
"Microsoft Corporation" → Azure (account name often `…@subscription`),
"Google Cloud Platform" / "Google LLC" → GCP, "Oracle Cloud" → OracleCloud.

`account_number` — provider-specific identifier:
- AWS: 12-digit account number (preserve all 12, including leading zeros)
- Azure: subscription GUID (8-4-4-4-12 format)
- GCP: project ID (alphanumeric, hyphens allowed)
- Oracle: tenancy OCID

`charges_by_service` — one row per service line. Normalise service names
by stripping the provider prefix:
- "Amazon EC2 - On Demand" → service=EC2, region present separately
- "Microsoft Compute Engine" → ComputeEngine
- "Cloud Storage" (GCP) → CloudStorage
- "S3 - Standard" → S3
- "Lambda" → Lambda

Keep `region` separate (us-east-1, eu-west-1, global). `usage_unit`
should be the natural unit ("hr", "GB", "request", "month").

Financials:
- `subtotal` — pre-discount, pre-tax
- `discounts` — negative number; capture EDP/committed-spend/private-pricing
- `tax` — sales tax if applicable
- `total` — what the customer actually owes
- `currency` — ISO 4217
- `usd_total` — convert to USD using booking-date FX (leave null if not the analyst's job)

`cost_center` / `gl_code` — leave null at extraction time; the orchestrator
resolves them from `tenants.config.cost_center_map` post-extraction.

Return JSON only.
