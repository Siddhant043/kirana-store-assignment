# Preferences skill

Standing Owner Preferences and Shop Profile survive across sessions. Conversation history is ephemeral; Preferences and Shop Profile are durable in Postgres.

## Tools

| Owner says | Tool | Notes |
|------------|------|-------|
| "always use UPI", "default payment is cash" | `set_preference` | `preference_key=default_payment_mode`, value `cash` \| `upi` \| `card` \| `khata`. |
| "when I say atta I mean …" | `set_preference` | After `find_product`, key `preferred_product:<normalized_query>`, value grounded `product_id` as a string. |
| "send my weekly deck Monday 9am IST" | `set_preference` | `preference_key=weekly_analysis_deck_schedule`, value like `mon 09:00` (day + 24h time, IST). |
| "what are my defaults?" | `get_preferences` | List all Preferences for this Owner. |
| "my shop is …", GSTIN | `set_shop_profile` | Shop identity — use documents tools, not Preferences. |

The Owner's Telegram `chat_id` is stored as Preference `owner_chat_id` automatically on each message (for scheduled delivery). Do not invent a chat id.

## Payment Mode defaults vs one-Bill override

- Standing default → `set_preference` with `default_payment_mode`.
- One Bill only ("…cash this time") → pass explicit `payment_mode` to `finalize_bill`; do **not** call `set_preference`.
- Omitting `payment_mode` on `finalize_bill` uses the stored default when present.

## `/new`

`/new` clears ephemeral conversation session only. Preferences and Shop Profile are re-injected on the next turn — they are not wiped.

## Domain language

Use: Owner, Preference, Shop Profile, Payment Mode, Product, `product_id`. Avoid: settings, config, account, SKU (as a synonym for Product).
