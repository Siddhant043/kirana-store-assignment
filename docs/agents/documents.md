# Documents skill

Use documents tools for Shop Profile, GST invoice PDFs, and analysis decks. Invoice PDFs and decks format stored Bill / analytics figures only — never invent or recompute GST.

## Shop Profile

| Owner says | Tool | Notes |
|------------|------|-------|
| "my shop is …", "set GSTIN …" | `set_shop_profile` | Persist shop name, address, GSTIN for invoice headers. |
| "use this logo …", "brand color #1A73E8" | `set_shop_profile` | Optional `logo_url` (image URL/path) and `accent_color` (`#RRGGBB`). Omit to keep existing branding; empty string clears. |
| "what's my shop profile?" | `get_shop_profile` | Read current Shop Profile including branding. |

A Shop Profile must exist before generating an invoice PDF. If `send_invoice_pdf` refuses with `shop_profile_missing`, ask the owner for shop name and GSTIN, call `set_shop_profile`, then retry. Logo and accent color are presentation-only — they do not change GST fields on the invoice.

## Invoice PDF

| Owner says | Tool | Notes |
|------------|------|-------|
| "send me that bill as a PDF", "invoice PDF" | `send_invoice_pdf` | Omit ids → most recent Bill for this chat. Pass `bill_id` or `invoice_number` when the owner specifies. |
| "which bill?", "find invoice …" | `find_bill` | Resolve without sending. |

`send_invoice_pdf` generates the PDF and sends it as a Telegram document. Confirm briefly after the tool succeeds (invoice number). Do not invent totals — the PDF uses finalized Bill figures.

## Analysis deck

| Owner says | Tool | Notes |
|------------|------|-------|
| "make this week's sales analysis deck", "analysis PPTX" | `send_analysis_deck` | Rolling last 7 IST days by default. Optional `day_count`. |

The deck includes sales trend, top items (revenue and quantity), Payment Mode mix, GST collected by GST Slab, stock health (Reorder Level), and an Insights slide. Insights are composed only from analytics figures — never estimate.

## Domain language

Use: Bill, Line, HSN Code, GST Slab, Round-off, Shop Profile, Khata, Customer, Payment Mode, Reorder Level. Avoid: receipt, order, invoice (as a synonym for Bill — the PDF is an invoice *document* of a Bill).
