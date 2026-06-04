# Supplier invoice extraction guidance

A supplier's invoice to the buyer — what should be paid after delivery.

Required:
- `buyer`, `supplier`, `po_number` (must match the PO this invoice bills)
- `invoice_number` — the supplier's invoice reference
- `document_date` — invoice issue date

`line_items` — what's being billed:
- Same shape as the PO: `part_number`, `description`, `quantity`,
  `uom`, `unit_price`, `amount`

Financials:
- `subtotal`, `tax`, `shipping`, `total`
- `currency` — ISO 4217

Return JSON only.
