# Purchase order extraction guidance

A buyer's commitment to a supplier.

Required:
- `buyer` — issuing organisation
- `supplier` — receiving organisation
- `po_number` — the PO number printed prominently on the document
- `document_date` — issue date
- `promised_delivery_date` — supplier's commit date (look for
  "Required by", "Promised", or "Need by")

`line_items` — every row. Per row:
- `part_number` — manufacturer or buyer's part number (preserve case)
- `description` — text description
- `quantity` — numeric
- `uom` — unit of measure normalised to canonical short code:
  ea/each → ea, pcs → ea, kg/kilogram → kg, lb/pound → lb,
  m/meter → m, ft/foot → ft, in/inch → in, L/litre → L, gal/gallon → gal
- `unit_price`
- `amount` — quantity × unit_price

Financials at the bottom:
- `subtotal` (sum of line item amounts)
- `tax`
- `shipping`
- `total` = subtotal + tax + shipping

`ship_to` / `bill_to` — addresses if present.

Return JSON only.
