# Analytics skill

Use analytics tools for sales summaries, Daily Close, and velocity-aware reorder suggestions. All figures are read-only aggregates from finalized Bills and current Product stock.

## When to use which tool

| Owner says | Tool | Notes |
|------------|------|-------|
| "today's sales?", "close the day", "daily close" | `daily_close` | Omit `business_date` for today (IST). Pass `YYYY-MM-DD` for a past IST business day. |
| "this week", "weekly sales", "last 7 days" | `weekly_sales_report` | Rolling last 7 IST calendar days including today. |
| "what should I reorder?", "what's running low based on how fast it's selling?" | `reorder_suggestions` | Ranks Products below Reorder Level by estimated days of stock from recent sales velocity. Prefer this over plain `list_low_stock` when the Owner cares about sell-through speed. |

## Daily Close is read-only

Daily Close is a **read-only** report. Never mutate Bills, stock, or Khata when closing the day. Re-asking returns the same figures for the same business date.

Explain totals in plain language:
- **total sales** — sum of finalized Bill totals (integer paise)
- **tax collected** — CGST + SGST from finalized Bills
- **payment mode split** — cash, UPI, card, khata totals
- **top items** — best sellers by revenue in the period

## Reorder suggestions

`reorder_suggestions` is read-only and grounded only on current stock + finalized Bill lines (never invent Products). Explain **days of stock remaining** when `basis` is `sales_velocity`. When `basis` is `reorder_level`, the Product had no recent sales and is flagged solely because quantity is below Reorder Level.

## Domain language

Use: Daily Close, Bill, Payment Mode, Khata (credit), Reorder Level, Product. Avoid: "end of day", "cashup", "EOD settlement", "min stock", "par level".

## Timezone

All business dates are **Asia/Kolkata (IST)**. A late-night sale at 11:45 PM IST belongs to that IST calendar day, not the next UTC day.
