# Documents skill

Use documents tools for Shop Profile and GST invoice PDFs. Invoice PDFs format stored Bill and Line values only — never recompute GST.

## Shop Profile

| Owner says | Tool | Notes |
|------------|------|-------|
| "my shop is …", "set GSTIN …" | `set_shop_profile` | Persist shop name, address, GSTIN for invoice headers. |
| "what's my shop profile?" | `get_shop_profile` | Read current Shop Profile. |

A Shop Profile must exist before generating an invoice PDF. If `send_invoice_pdf` refuses with `shop_profile_missing`, ask the owner for shop name and GSTIN, call `set_shop_profile`, then retry.

## Invoice PDF

| Owner says | Tool | Notes |
|------------|------|-------|
| "send me that bill as a PDF", "invoice PDF" | `send_invoice_pdf` | Omit ids → most recent Bill for this chat. Pass `bill_id` or `invoice_number` when the owner specifies. |
| "which bill?", "find invoice …" | `find_bill` | Resolve without sending. |

`send_invoice_pdf` generates the PDF and sends it as a Telegram document. Confirm briefly after the tool succeeds (invoice number). Do not invent totals — the PDF uses finalized Bill figures.

## Domain language

Use: Bill, Line, HSN Code, GST Slab, Round-off, Shop Profile, Khata, Customer. Avoid: receipt, order, invoice (as a synonym for Bill — the PDF is an invoice *document* of a Bill).
