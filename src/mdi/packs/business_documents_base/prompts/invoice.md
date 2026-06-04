# Invoice extraction guidance

Extract the following fields from an invoice. Use the schema's expected types. If the
document does not provide a value, set it to null with confidence 0.

- vendor: the issuing party (look in the header / "From" / letterhead).
- customer: the billed party (look for "Bill To" / "Customer").
- document_number: the invoice number.
- document_date: the invoice issue date.
- due_date: the payment due date.
- currency: the ISO 4217 code; infer from the symbol if missing (USD for $, EUR for €).
- subtotal, tax, total: the bottom-line amounts. Total should equal subtotal + tax.
- line_items: array of {description, quantity, unit_price, amount}.

If the document is multi-page, prefer the page that contains the totals.

Return JSON only.
