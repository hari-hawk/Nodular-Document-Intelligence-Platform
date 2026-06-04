# Purchase order extraction guidance

A purchase order is the buyer's commitment to a vendor.

- vendor: the seller / supplier.
- customer: the buyer (issuer of the PO).
- document_number: the PO number.
- document_date: the PO issue date.
- due_date: the requested delivery date if present, else expiry.
- currency: ISO 4217.
- subtotal, tax, total.
- line_items: {description, quantity, unit_price, amount}.

Return JSON only.
