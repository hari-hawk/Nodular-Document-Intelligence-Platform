# Cloud cost-explorer / CUR export extraction guidance

A cost-and-usage CSV/JSON dump (AWS CUR, Azure Cost Management export,
GCP billing export). These are LARGE — often tabular with thousands of
rows.

The right approach for these is summarization, not row-by-row extraction:
- `provider`, `account_number`, `billing_period_start/end` — header lines
  or filename conventions.
- `charges_by_service` — aggregate by service; emit one row per
  (service, region) combination with `charge` summed across the period.
- `usage_unit` is often heterogeneous; use the dominant unit.
- Skip `invoice_number`, `due_date` — these don't apply to raw exports.

Return JSON only.
