# Core-first phased delivery; stretches layered in ADR order

The build ships the core end-to-end and rock-solid before any stretch feature, then layers stretches in the order their ADRs were recorded. Rationale: the core (grounding, oversell, GST, multi-turn drafts, idempotency, concurrency, khata, memory, PDF, PPTX) is what the assignment grades hardest, and every stretch depends on core primitives already being trustworthy (e.g. FEFO extends the stock/oversell core; the scheduler reuses the deck generator and preferences; voice/barcode are input adapters into the existing loop). Shipping order:

1. **Core** — schema + migrations, inventory/billing/khata/analytics/documents/preferences skills, the control loop, oversell/idempotency/concurrency guarantees, GST engine, invoice PDF, analytics deck, cross-session memory. Tested (pytest + Postgres testcontainer) before moving on.
2. **FEFO batches** (ADR-0012) — reshapes the stock core, so it comes first among stretches while the stock code is fresh.
3. **Scheduler** (ADR-0013) — weekly deck auto-send + khata reminders.
4. **Voice** (ADR-0014) — hosted Whisper input adapter.
5. **Barcode / photo** (ADR-0015) — pyzbar tool + vision→find_product.
6. **Multi-language** (ADR-0016) — native-script aliases + Unicode invoices.
7. **Branded invoice** and **reorder suggestions** — fall out of existing choices (Jinja/CSS; stock_ledger velocity), folded in opportunistically.

Each phase is independently demoable and leaves the bot shippable, so the live deadline is never blocked on an in-progress stretch.
