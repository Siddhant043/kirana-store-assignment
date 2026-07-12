# Supermarket Ops Agent — Kirana Store, run from a chat window

**Telegram bot: [@Kiranawala_bot](https://t.me/Kiranawala_bot)**

A conversational agent that runs a small Indian kirana (grocery) store end-to-end —
receiving stock, cutting GST-correct bills, running customer credit (khata), closing
the day, and generating real PDF invoices and PPTX analysis decks — entirely through
plain-language Telegram messages. There is no admin panel and no web app. The chat
is the product.

See [`CONTEXT.md`](CONTEXT.md) for domain vocabulary and [`docs/adr/`](docs/adr/) for
architectural decisions.

---

## Table of contents

1. [The brief, in one line](#the-brief-in-one-line)
2. [Harness — why the Claude Agent SDK](#harness--why-the-claude-agent-sdk)
3. [Control loop](#control-loop)
4. [Skill / tool design](#skill--tool-design)
5. [The domain model](#the-domain-model)
6. [How each hard part is solved](#how-each-hard-part-is-solved)
7. [What the owner can do (capability map)](#what-the-owner-can-do-capability-map)
8. [Setup & running it yourself](#setup--running-it-yourself)
9. [Demo script](#demo-script)
10. [Stretch goals implemented](#stretch-goals-implemented)
11. [Stretch goals not attempted](#stretch-goals-not-attempted)
12. [Known limitations / what I'd harden next](#known-limitations--what-id-harden-next)

---

## The brief, in one line

> Chat as the interface, an LLM as the reasoning brain, and a set of small,
> business-rule-enforcing tools as the execution layer — no keyword router,
> no CRUD forms.

Everything below explains how that's actually built, not just described.

---

## Harness — why the Claude Agent SDK

I built this on the **Claude Agent SDK (Python)** — `query()` + in-process MCP
`tool()` servers — rather than the Vercel AI SDK or a deep-agent framework, because:

- It gives a real observe → reason → act control loop with native multi-tool
  chaining in a single turn (e.g. `find_product` → `add_line` → `add_line` →
  `view_draft` → `finalize_bill`) without a hand-rolled orchestrator or
  LangGraph-style node-per-command state machine (explicitly what the brief’s §5
  asks for — and what it asks us _not_ to build).
- Tool schemas are first-class; skill playbooks live as markdown
  (`docs/agents/*.md`) concatenated into the system prompt so the model knows
  _how_ to compose tools, while the tools themselves enforce the rules.
- Python has the strongest ecosystem for the two required artifacts: **WeasyPrint**
  for GST-correct invoice PDFs and **python-pptx** for analysis decks with real
  charts.

**Rejected alternatives:** Vercel AI SDK / TypeScript (weaker PDF/PPTX story for
this domain), deep-agent frameworks (thinner justification for a single-shop
bot), and any regex/intent router in front of the model.

**Model note:** the primary loop runs on **`claude-sonnet-5`** by default
(`CLAUDE_MODEL_ID` in `.env`). Voice notes go through a hosted Whisper endpoint
(`WHISPER_API_KEY`, OpenAI-compatible — OpenAI or Groq). Switching the Claude
model is a one-line env change; the harness and tool surface stay the same.

---

## Control loop

1. Telegram delivers updates via **long-polling** (`src/main.py`, aiogram). On
   startup the bot deletes any webhook so polling owns the feed — no public
   HTTPS endpoint required for the core path.
2. Every update hits `UpdateHandler.handle` (`src/bot/handler.py`).
3. **Idempotency claim first, before any business logic:**
   `ProcessedUpdatesStore.try_record(update_id)` inserts the Telegram
   `update_id`. A duplicate means Telegram redelivered — we stop immediately
   and never re-enter the agent loop ([ADR-0004](docs/adr/0004-idempotency-two-layers.md)).
4. `/new` is special-cased only to clear the ephemeral Claude session id for
   that chat (`agent.clear_session`). It does **not** touch Preferences or Shop
   Profile — that is the point of hard part #9
   ([ADR-0007](docs/adr/0007-cross-session-memory.md),
   [ADR-0009](docs/adr/0009-ephemeral-sessions-durable-store.md)).
5. Voice notes are transcribed (hosted Whisper) and photos are downloaded; both
   become a text (or multimodal) prompt before the harness. Failure to
   transcribe gets a fixed apology — still no intent router.
6. Everything else is handed to `ClaudeAgentHarness.reply`
   (`src/agent/harness.py`), which:
   - loads standing Preferences + Shop Profile from Postgres and appends them
     to the system prompt as plain facts,
   - resumes the prior Claude session for that `chat_id` when one exists,
   - calls the Claude Agent SDK `query()` with the full MCP tool allowlist.
7. The model reasons over the message, calls whichever tools it needs —
   observe → reason → act → feed result back → continue — and produces a final
   natural-language reply. Document tools (`send_invoice_pdf`,
   `send_analysis_deck`) push files to Telegram themselves via `sendDocument`.

**There is no keyword/regex router anywhere in this path** — the handler passes
owner text (or transcribed/caption text) straight to the model; the harness
never branches on message content beyond `/new`.

---

## Skill / tool design

Skills are markdown playbooks under `docs/agents/` (inventory, billing, khata,
analytics, documents, preferences). They are loaded into the system prompt at
startup. Tools are thin MCP wrappers in `src/tools/` that open a DB session,
call a fat domain service in `src/domain/`, and return structured JSON
(facts, `refused`, or `requires_confirmation`). Business rules live where the
data changes — not in the prompt.

Wiring and the allowlist live in `src/tools/mcp_server.py`. GST math has a
single source of truth: `src/domain/pricing.py` (integer paise).

| Area                                                                | Tools (MCP)                                                                                                                                  | Responsibility                                                                   |
| ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Inventory (`inventory_tools.py` → `inventory.py`, `barcode.py`)     | `find_product`, `scan_barcode`, `prepare_photo_product`, `add_product`, `receive_stock`, `get_stock`, `list_low_stock`, `list_expiring_soon` | Product grounding, stock-in as Batches, low stock / expiry                       |
| Billing (`billing_tools.py` → `billing.py`, `pricing.py`)           | `open_draft_bill`, `add_line`, `update_line`, `remove_line`, `view_draft`, `finalize_bill`                                                   | Multi-turn Draft Bill lifecycle; stock untouched until finalize                  |
| Khata (`khata_tools.py` → `khata.py`)                               | `find_or_create_customer`, `add_khata_charge`, `record_payment`, `get_khata_balance`                                                         | Customer credit ledger + existence / overpayment guardrails                      |
| Analytics (`analytics_tools.py` → `analytics.py`)                   | `daily_close`, `weekly_sales_report`, `reorder_suggestions`                                                                                  | Day close, weekly figures, velocity-aware reorder                                |
| Documents (`documents_tools.py` → `invoice.py`, `analysis_deck.py`) | `set_shop_profile`, `get_shop_profile`, `find_bill`, `send_invoice_pdf`, `send_analysis_deck`                                                | Shop identity on invoices; real PDF / PPTX to Telegram                           |
| Preferences (`preferences_tools.py` → `preferences.py`)             | `set_preference`, `get_preferences`                                                                                                          | Cross-session memory (hard part #9) + schedule keys for the in-process scheduler |

The model composes these tools; there is no mega-tool that “runs the store.”

---

## The domain model

Modeled as a real kirana store, not a generic products table
(see [`CONTEXT.md`](CONTEXT.md)):

- **Currency:** ₹ throughout. All money is **integer paise** — never floats
  ([ADR-0006](docs/adr/0006-mrp-tax-inclusive-integer-paise.md)).
- **Product:** cost price, MRP (tax-inclusive), quantity, reorder level, GST
  slab, HSN. Packaged SKUs (Aashirvaad Atta 5kg, Maggi 70g, …) vs loose
  commodities (sugar / rice / dal by kg or litre).
- **Draft Bill vs Bill:** a Draft Bill is persisted, editable, and holds no
  stock. Finalizing mints an immutable Bill, decrements stock, and assigns an
  invoice number.
- **Line:** always a grounded `product_id` + quantity + derived tax breakup —
  never a free-text name on a money-touching write
  ([ADR-0008](docs/adr/0008-structural-grounding-product-id.md)).
- **GST:** per-Product slab (0 / 5 / 12 / 18). Taxable value is derived _out of_
  MRP; GST splits evenly into CGST + SGST (intra-state); bill-level round-off
  to the nearest rupee.
- **Payments:** Cash / UPI / Card on the Bill, plus **khata** as a first-class
  payment mode at finalize ([ADR-0011](docs/adr/0011-khata-as-payment-mode.md)).
- **Khata:** Customer + append-only Khata Entries; balance is the sum of
  charges and payments.
- **Batches / FEFO:** stock is `stock_batches` rows (qty, cost, optional
  expiry). Sales consume earliest-expiry first; sellable qty excludes expired
  batches ([ADR-0012](docs/adr/0012-fefo-batch-tracking.md)).
- **Stock ledger:** append-only audit of every batch quantity change
  ([ADR-0005](docs/adr/0005-concurrency-locking-and-stock-ledger.md)).
- **Preference / Shop Profile:** durable owner settings and invoice identity,
  outside the conversation window.

---

## How each hard part is solved

1. **Grounding.** Price-bearing tools take a structural `product_id`, never a
   free-text name ([ADR-0008](docs/adr/0008-structural-grounding-product-id.md)).
   The model must call `find_product` (pg_trgm + aliases) — or `scan_barcode` /
   photo confirm — before `add_line` / `receive_stock`. MRP, GST slab, and HSN
   are read from the Product row at finalize; the model does not invent them.

2. **Oversell guard.** `add_line` may soft-warn on availability, but the
   **authoritative** check is inside `finalize_bill`: after ordered row locks,
   requested qty is compared to sellable (non-expired) batch qty and refused
   with `reason="oversell"` at the tool/DB layer
   ([ADR-0003](docs/adr/0003-drafts-persisted-no-reservation.md)). Stock is
   never reserved on the draft.

3. **GST correctness.** `src/domain/pricing.py` derives taxable value from
   tax-inclusive MRP, splits GST into CGST/SGST, rounds half-up in paise, and
   applies bill-level round-off ([ADR-0006](docs/adr/0006-mrp-tax-inclusive-integer-paise.md)).
   The invoice PDF renders stored bill figures — it does not re-invent tax.

4. **Multi-turn bills.** Draft bills and lines live in Postgres keyed by
   `chat_id`, not in chat memory. `add_line` / `update_line` / `remove_line`
   mutate the open draft across messages; `Product` / batch qty is untouched
   until `finalize_bill` ([ADR-0003](docs/adr/0003-drafts-persisted-no-reservation.md),
   [ADR-0009](docs/adr/0009-ephemeral-sessions-durable-store.md)).

5. **Idempotency.** Two layers ([ADR-0004](docs/adr/0004-idempotency-two-layers.md)):
   (a) transport — unique `update_id` in `processed_updates` before the agent
   runs; (b) domain — `finalize_bill` locks the draft; if already finalized, it
   returns the existing bill with `idempotent_replay=True` instead of
   double-decrementing stock.

6. **Concurrency.** Stock mutations take `SELECT … FOR UPDATE` on products
   (and batches) in sorted id order, then append `stock_ledger` rows
   ([ADR-0005](docs/adr/0005-concurrency-locking-and-stock-ledger.md)).
   Concurrent finalize paths are covered by pytest
   (`test_concurrent_finalize_*` in billing / FEFO tests) so two sales cannot
   drive batch qty negative.

7. **Guardrails.** Enforced in domain services, not hoped for in the prompt:
   sell-below-cost requires confirmation; missing / phantom khata is refused;
   overpayment and new-customer create are confirm gates; photo vision goes
   through `prepare_photo_product`. There is intentionally **no** “delete
   stock” tool.

8. **Real artifacts.** `send_invoice_pdf` renders Jinja
   `templates/invoice.html` through WeasyPrint (line items, per-slab CGST/SGST
   breakup, shop profile). `send_analysis_deck` builds a real `.pptx` with
   native charts via python-pptx — not screenshots or plain text.

9. **Memory across sessions.** Preferences and Shop Profile are Postgres rows
   keyed by owner Telegram user id, loaded every turn into the system prompt
   (`render_standing_memory`). `/new` clears only the in-memory Claude session
   id — standing defaults (payment mode, preferred atta `product_id`, shop
   GSTIN, weekly-deck schedule) survive by construction
   ([ADR-0007](docs/adr/0007-cross-session-memory.md)).

---

## What the owner can do (capability map)

These are capabilities the model composes from tools — not fixed commands.

| Intent                | Example message                                                            | Tool(s) involved                                                                     |
| --------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Receive stock         | _"50 packets of Maggi came in, cost ₹12, MRP ₹14"_                         | `find_product` → `receive_stock`                                                     |
| Add a new product     | _"new item: Amul Butter 100g, GST 12%, MRP ₹62"_                           | `add_product`                                                                        |
| Cut a bill            | _"make a bill: 2kg sugar, 1 Aashirvaad atta 5kg, 4 Maggi, UPI"_            | `open_draft_bill` → `find_product` / `add_line` (×N) → `finalize_bill`               |
| Edit a bill mid-build | _"drop the butter, make it 6 Maggi"_                                       | `remove_line`, `update_line` / `add_line`                                            |
| Stock query           | _"how much sugar is left?"_                                                | `find_product` → `get_stock`                                                         |
| Low-stock / reorder   | _"what's running out?"_                                                    | `list_low_stock`, `reorder_suggestions`                                              |
| Credit (khata)        | _"put ₹500 on Ramesh's credit" / "Ramesh paid ₹300" / "Ramesh's balance?"_ | `find_or_create_customer`, `add_khata_charge`, `record_payment`, `get_khata_balance` |
| Daily close           | _"today's sales?" / "close the day"_                                       | `daily_close`                                                                        |
| Invoice as PDF        | _"send me that bill as a PDF"_                                             | `find_bill` → `send_invoice_pdf`                                                     |
| Analysis deck         | _"make this week's sales analysis deck"_                                   | `send_analysis_deck` (uses analytics under the hood)                                 |
| Set a preference      | _"always assume UPI unless I say cash"_                                    | `set_preference`                                                                     |
| Shop identity         | _"shop name is …, GSTIN is …"_                                             | `set_shop_profile`                                                                   |

When a request is genuinely ambiguous (e.g. _"add atta"_ with multiple atta
products), the model asks a clarifying question from skill instructions and
`find_product`’s `ambiguous` result — not a hardcoded branch in the handler.

---

## Setup & running it yourself

### Prerequisites

- Docker and Docker Compose
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- An Anthropic API key
- A hosted Whisper API key (OpenAI or Groq OpenAI-compatible) for voice notes

### Environment

```bash
cp .env.example .env
# Fill in at least:
#   TELEGRAM_BOT_TOKEN=
#   ANTHROPIC_API_KEY=
#   WHISPER_API_KEY=
```

### Run locally

```bash
docker compose up --build
```

The bot long-polls Telegram, runs Alembic migrations on startup, and starts the
in-process APScheduler for weekly deck / khata reminder jobs.

Message the live bot (handle at the top of this README) while it is kept
running for review.

### Development

```bash
uv sync --group dev
uv run ruff check .
uv run mypy src
uv run pytest
```

---

## Demo script

The recorded walkthrough covers, in order:

1. Receive stock for a couple of SKUs.
2. Build a multi-item bill across several messages, including an edit
   ("drop the butter, make it 6 Maggi").
3. Attempt to oversell a product — refused at the tool layer.
4. A full khata cycle: put an amount on a customer's credit, check their
   balance, record a payment.
5. Generate a PDF invoice for a finalized bill.
6. Generate a PPTX analysis deck for the week.
7. Set a standing preference, send `/new`, and show the preference still
   applies in the fresh conversation.

---

## Stretch goals implemented

Per the brief’s §7, all eight optional stretch goals are wired in — each is a
real feature, not a stub:

1. **Branded / templated invoice PDFs.** `templates/invoice.html` is a designed
   tax invoice (letterhead, optional logo, accent color from Shop Profile) rendered
   by WeasyPrint — not a plain table dump.
2. **Scheduled weekly analysis deck, auto-sent.** An in-process
   `AsyncIOScheduler` ([ADR-0013](docs/adr/0013-in-process-scheduler.md)) runs
   `run_weekly_analysis_deck_job` on a preference-configured IST cron and pushes
   the PPTX to the owner’s Telegram chat.
3. **Reorder suggestions from sales velocity.** `reorder_suggestions` looks at a
   rolling sales window, estimates daily velocity and days-of-stock, and falls
   back to reorder-level when there is no sales history.
4. **Expiry / batch tracking with FEFO.** Stock is batches with optional expiry;
   finalize consumes earliest-expiry first; `list_expiring_soon` surfaces near
   expiry ([ADR-0012](docs/adr/0012-fefo-batch-tracking.md)).
5. **Voice-note orders.** Handler downloads the voice file, transcribes via
   hosted Whisper (`src/domain/voice.py`), then feeds the text through the
   _same_ harness path as a typed message ([ADR-0014](docs/adr/0014-voice-transcription-and-resource-budget.md)).
6. **Multi-language (Hindi / Tamil).** The system prompt mirrors the owner’s
   language; `aliases` + fuzzy `find_product` resolve native/transliterated
   names; invoices stay structurally English (GST legal labels) with Unicode
   free-text via Noto fonts in Docker
   ([ADR-0016](docs/adr/0016-multilingual-scope.md)).
7. **Barcode / product photo → identify item.** Photos try `scan_barcode`
   (pyzbar) first; otherwise vision → `find_product` → `prepare_photo_product`
   confirm gate before `add_line`
   ([ADR-0015](docs/adr/0015-image-input-barcode-and-vision.md)).
8. **Khata payment reminders.** Scheduled job digests outstanding khata and
   messages the **owner** (never customers) on a preference-driven IST schedule.

---

## Stretch goals not attempted

None of the brief’s §7 stretches were left unattempted. Further hardening
(distributed scheduling, fully translated GST invoices, multi-shop tenancy) is
out of scope for v1 — see limitations below.

---

## Known limitations / what I'd harden next

- **Ephemeral conversations.** Claude session ids live in process memory. A
  restart drops chat continuity; Draft Bills, stock, khata, and Preferences in
  Postgres survive and drafts remain recoverable via `view_draft`.
- **Scheduler misfires.** APScheduler is in-process with a short grace window
  ([ADR-0013](docs/adr/0013-in-process-scheduler.md)). If the process is down
  when a job is due, that firing is skipped; the owner can still request a deck
  on demand.
- **Single shop / single owner.** One catalog and one owner Telegram identity —
  matching the brief, not a multi-tenant SaaS.
- **PPTX native script.** Invoices embed Noto fonts for Devanagari/Tamil;
  python-pptx font embedding is best-effort, so decks stay label-light for
  non-Latin content.
- **Draft bill UX in chat.** Structured draft state is returned to the model;
  the owner-facing summary is composed as natural-language reply text rather
  than a fixed Telegram-native table.
