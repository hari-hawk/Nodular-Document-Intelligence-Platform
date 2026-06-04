# Quality / inspection report extraction guidance

A QC report or Certificate of Analysis (CoA) for a delivered lot.

Required:
- `buyer`, `supplier`
- `po_number` (links the lot back to the PO)
- `lot_number` — the lot/batch identifier
- `inspection_result` — one of: `pass`, `fail`, `conditional`

`line_items` — items inspected:
- `part_number`, `description`, `quantity`, `uom`
- Skip `unit_price` / `amount`

`document_date` — inspection date.

Return JSON only.
