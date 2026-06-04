# Bill of Lading extraction guidance

A BoL is the carrier's receipt + the buyer's evidence that goods
arrived. It pairs with a PO and (later) a supplier invoice.

Required:
- `buyer`, `supplier`, `po_number` (the BoL references the PO)
- `bol_number` — the BoL's own identifier
- `actual_delivery_date` — the date received (NOT the promised date)
- `line_items` — what was delivered:
  - `part_number`, `description`, `quantity`, `uom`
  - `unit_price` and `amount` are usually NOT on a BoL; leave null

`ship_to` — destination address.

Financial fields (`subtotal`, `tax`, `total`) are typically null on a BoL.

Return JSON only.
