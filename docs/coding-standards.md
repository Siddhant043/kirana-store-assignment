# Coding Standards

Conventions for writing Python and SQL in this repo. Business invariants live in ADRs; domain vocabulary lives in `CONTEXT.md`. This doc states the **coding implications** — link outward rather than duplicating decision prose.

## Audience & related docs

| Audience | Use this doc for |
|----------|------------------|
| **AI agents** | Hard rules before writing or reviewing code |
| **Author** | Checklist while building the take-home |
| **Reviewers** | Signals that correctness and maintainability were considered |

| Doc | Owns |
|-----|------|
| [`CONTEXT.md`](../CONTEXT.md) | Domain glossary — Bill, Draft Bill, Khata, Product, Line, … |
| [`docs/adr/`](adr/) | Architectural decisions and rationale |
| [`AGENTS.md`](../AGENTS.md) | Agent workflow (issues, triage, domain docs) — not code style |

## General principles

Adapted from project-wide engineering values; expressed in Python idioms for this codebase.

- **KISS / YAGNI** — smallest correct diff. No speculative abstractions, factories, or plugin systems without a current use case.
- **SRP** — thin Telegram/agent handlers; business rules in tools and domain modules; persistence in the DB layer.
- **Enforce at the boundary** — oversell guards, GST math, idempotency, and khata rules run where data changes, not in the system prompt.
- **Explicit errors** — return structured tool errors the model can relay to the owner; never swallow exceptions silently.
- **Dependency injection** — wire DB pools, config, and clients in the composition root (`main`, bot startup), not inside individual tools.
- **Self-documenting code** — descriptive names (`finalize_bill`, `stock_ledger`); comments only for non-obvious invariants or transaction ordering.

---

## Hard rules (must / must-not)

### Domain & naming

- **MUST** use terms from [`CONTEXT.md`](../CONTEXT.md) in code, schemas, tools, and user-facing messages (Bill, Draft Bill, Khata, Product, Line, Owner, …).
- **MUST NOT** use avoided synonyms in identifiers or APIs: `order`, `cart`, `account`, `tab`, `user` (for Owner), `transaction`, `receipt`, `SKU` (except as the identifier field name if needed).

### Structural grounding — [ADR-0008](adr/0008-structural-grounding-product-id.md)

- **MUST** accept `product_id` on every price-bearing tool (`add_line`, stock-in, etc.) — never a free-text product name.
- **MUST** resolve products through `find_product` before `add_line`; the model disambiguates when `ambiguous` is returned.
- **MUST NOT** invent prices, GST slabs, or HSN codes — they always originate from the grounded product row.

### Money & GST — [ADR-0006](adr/0006-mrp-tax-inclusive-integer-paise.md)

- **MUST** store and compute all monetary values as **integer paise**.
- **MUST** treat MRP as tax-inclusive; derive taxable value *out of* MRP, never add GST on top.
- **MUST** implement GST math in a shared `pricing` module called by billing tools — **never** in the model or prompt.

### Draft bills — [ADR-0003](adr/0003-drafts-persisted-no-reservation.md)

- **MUST** persist draft bills and lines in Postgres — not in conversation memory alone.
- **MUST NOT** reserve stock on `add_line`; soft availability check only.
- **MUST** run the authoritative oversell guard inside `finalize_bill`'s locked transaction.

### Concurrency & stock — [ADR-0005](adr/0005-concurrency-locking-and-stock-ledger.md)

- **MUST** wrap every stock mutation (`finalize_bill`, `receive_stock`, `stock_adjustment`) in a transaction with `SELECT … FOR UPDATE` on affected product rows.
- **MUST** lock product rows in **sorted `product_id` order** when a operation touches multiple SKUs (deadlock prevention).
- **MUST** append every quantity change to `stock_ledger` (`delta`, `reason`, `ref_id`, `balance_after`, `ts`).

### Idempotency — [ADR-0004](adr/0004-idempotency-two-layers.md)

- **MUST** dedupe Telegram `update_id` at the edge via `processed_updates` before entering the agent loop.
- **MUST** make `finalize_bill` idempotent via the draft's `open → finalized` state transition under row lock; a retry returns the existing `bill_id` without re-decrementing stock.

### Cross-session memory — [ADR-0007](adr/0007-cross-session-memory.md)

- **MUST** persist preferences and shop profile in Postgres keyed by Owner Telegram user id — outside the context window.
- **MUST** expose writes through tools (`set_preference`, …), not regex capture from chat.

### Agent vs tool boundary

- **MUST NOT** encode business rules in the system prompt and hope the model complies.
- **MUST NOT** implement a regex/keyword intent router that does the real work — the model orchestrates; tools enforce.
- Tools return facts and refusals; the model reasons, chains calls, and asks clarifying questions when tools report ambiguity.

---

## Conventions (should)

### Python

- Type hints on all public functions and tool schemas; avoid `Any` unless documented with justification.
- Use `async`/`await` for I/O-bound work (Telegram, Postgres, file generation).
- Suggested layout as code lands: `src/agent/` (harness loop), `src/tools/` (thin tool implementations), `src/domain/` (pricing, billing logic), `src/db/` (queries, migrations).
- One module per concern — e.g. `pricing.py`, `billing.py`, `stock.py`, `khata.py`.
- Tool return values are structured dicts with stable field names so the model can parse them reliably.
- Prefer `dataclass` / typed dicts for domain objects over loose dicts passing through layers.

### SQL

- Numbered, reviewable migrations; reversible where practical.
- All stock and billing mutations inside explicit transactions — no autocommit read-then-write.
- Table and column names match domain language: `draft_bills`, `draft_lines`, `bills`, `stock_ledger`, `khata_entries`, `processed_updates`.
- Use Postgres features chosen in ADRs: row-level locking, `pg_trgm` for product search.

### Tests

- **Unit tests** for `pricing` — GST slabs, CGST/SGST split, per-line rounding, bill-level round-off edge cases.
- **Integration tests** for oversell refusal, idempotent finalize on retry, concurrent finalize on overlapping SKUs.
- Test names describe behavior: `test_finalize_refuses_when_insufficient_stock`, `test_finalize_retry_returns_same_bill_id`.
- Add tests when fixing a hard-part bug; don't test trivial getters.

---

## Tooling (planned)

Config ships with the first code PR — this section records intent so agents don't bikeshed early.

| Tool | Enforces |
|------|----------|
| **ruff** | Lint + format (PEP 8, import order, line length) |
| **mypy** | Strict typing on `src/` |
| **pytest** | Unit and integration test runner |
| **pre-commit** | Run ruff + mypy + pytest on commit |

Until `pyproject.toml` exists, follow the hard rules and conventions in this doc manually.

---

## For reviewers

Quick signals that the implementation takes the hard parts seriously:

- Business rules live in tools and transactions, not prompts or regex routers.
- Money is integer paise; GST math is centralized in `pricing`, called by billing tools.
- Stock correctness uses ordered `FOR UPDATE` locks plus an append-only `stock_ledger`.
- Idempotency is two-layer: Telegram `update_id` dedup + draft state machine on finalize.
- Domain language matches [`CONTEXT.md`](../CONTEXT.md); billing is structurally grounded on `product_id`.
