# Analytics skill

Use analytics tools for sales summaries and Daily Close. All figures are read-only aggregates from finalized Bills.

## When to use which tool

| Owner says | Tool | Notes |
|------------|------|-------|
| "today's sales?", "close the day", "daily close" | `daily_close` | Omit `business_date` for today (IST). Pass `YYYY-MM-DD` for a past IST business day. |
| "this week", "weekly sales", "last 7 days" | `weekly_sales_report` | Rolling last 7 IST calendar days including today. |

## Daily Close is read-only

Daily Close is a **read-only** report. Never mutate Bills, stock, or Khata when closing the day. Re-asking returns the same figures for the same business date.

Explain totals in plain language:
- **total sales** — sum of finalized Bill totals (integer paise)
- **tax collected** — CGST + SGST from finalized Bills
- **payment mode split** — cash, UPI, card, khata totals
- **top items** — best sellers by revenue in the period

## Domain language

Use: Daily Close, Bill, Payment Mode, Khata (credit). Avoid: "end of day", "cashup", "EOD settlement".

## Timezone

All business dates are **Asia/Kolkata (IST)**. A late-night sale at 11:45 PM IST belongs to that IST calendar day, not the next UTC day.
