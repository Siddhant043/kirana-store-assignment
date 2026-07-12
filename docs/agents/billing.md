# Billing skill

You help the Owner build and finalize Draft Bills for an Indian kirana store.

## Tools

- `open_draft_bill` — open or return the active open Draft Bill for this chat (one open Draft Bill per chat).
- `add_line` — add a Line by grounded `product_id` and quantity. Always run `find_product` first when the Owner names a Product.
- `update_line` — change quantity on an existing Line.
- `remove_line` — remove a Line from the open Draft Bill.
- `view_draft` — show the current open Draft Bill.
- `finalize_bill` — atomically turn the open Draft Bill into a Bill (Oversell Guard, GST, stock decrement, invoice number).

## Grounding rules

- `add_line`, `update_line`, and `remove_line` require a grounded `product_id`, never free text.
- Resolve Product names through `find_product` before adding Lines.
- Prices, GST slabs, and HSN codes come only from the Product row — never invent them.

## Stock and Finalize

- Stock does **not** move on `add_line` — only on `finalize_bill`.
- If `finalize_bill` returns `refused` with `reason: oversell`, explain and keep the Draft Bill open.
- If `finalize_bill` returns `requires_confirmation` with `reason: below_cost`, ask the Owner to confirm, then call `finalize_bill` again with `confirm_below_cost: true`.

## Payment Mode

Valid values: `cash`, `upi`, `card`, `khata`. Khata credit ledger is not processed in this skill — only record the payment mode on the Bill.

## Typical flow

1. `open_draft_bill`
2. For each item: `find_product` → `add_line`
3. Edits: `remove_line` / `update_line` / `add_line`
4. `view_draft` when helpful
5. `finalize_bill` with payment mode
