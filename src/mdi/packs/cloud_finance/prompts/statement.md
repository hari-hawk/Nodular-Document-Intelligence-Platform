# Cloud statement extraction guidance

A cloud-provider account statement — aggregates one or more invoices
into a single billing-period view.

Same field shape as the invoice prompt; the differences:
- `invoice_number` may be a statement number instead — capture it.
- `charges_by_service` reflects period totals, not per-charge lines.
- The same `subtotal/discounts/tax/total/usd_total` block applies.

Return JSON only.
