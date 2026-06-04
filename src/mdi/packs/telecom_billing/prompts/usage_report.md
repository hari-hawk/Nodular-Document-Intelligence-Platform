# Telecom usage report extraction guidance

A usage report (often called CDR — call detail record — at the
aggregated level) shows traffic consumed in a billing period.

Required:
- `carrier`, `customer`, `account_number`.
- `service_period_start`, `service_period_end`.

Service lines (`service_lines`) — usage broken down by service_type:
- For voice: `quantity` = minutes, `mrc_total` = computed voice cost
- For data: `quantity` = GB / Mbps, `mrc_total` = computed data cost
- For SMS: `quantity` = message count, `mrc_total` = computed SMS cost

`phone_numbers` may appear as top-usage DIDs; emit E.164.

Totals if the report has a summary section:
- `subtotal`, `tax`, `total` for the period.

Return JSON only.
