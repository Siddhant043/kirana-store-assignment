# Ubiquitous Language

The shared vocabulary for the Supermarket Ops Agent — a Telegram agent that runs an Indian kirana store. Use these terms exactly in code, schemas, tools, and owner-facing text. The tighter glossary lives in [`CONTEXT.md`](CONTEXT.md); this document adds relationships, a worked dialogue, and the ambiguities to watch.

## Catalogue & stock

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Product** | A stocked item the shop sells, carrying cost price, MRP, GST slab, HSN, reorder level, and unit type. | item, SKU (see below) |
| **SKU** | The stable identifier of a Product — an attribute of a Product, never the Product itself. | product code |
| **Batch** | One intake of a Product held as its own row with quantity, cost price, and optional expiry; sold First-Expiry-First-Out. | lot, consignment |
| **Unit Type** | Whether a Product is `packaged` (integer count) or `loose` (decimal by kg/litre). | bulk, packaged good |
| **Stock Ledger** | The append-only record of every Batch quantity change (sale, stock-in, adjustment) with delta, reason, reference, and resulting balance. | stock log, history |
| **Alias** | An alternate or native-language term ("chini", "atta") that resolves to Product candidates during lookup. | synonym, keyword |
| **Reorder Level** | The quantity threshold below which a Product is "running out". | min stock, par level |
| **Barcode** | The EAN/UPC code on a Product's packaging, used for exact scan-based lookup. | UPC only, scan code |

## Billing

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Draft Bill** | An in-progress, editable bill (status `open`) that holds no stock until finalized. | cart, pending order |
| **Bill** | A finalized, immutable sale — created by finalizing a Draft Bill, decrementing stock and minting an invoice number. | order, transaction, receipt |
| **Line** | A single Product entry on a Draft Bill or Bill — a grounded `product_id`, a quantity, and the derived tax breakup. | item row, entry |
| **MRP** | The tax-inclusive maximum retail price the customer pays; taxable value and GST are derived *out of* it. | sell price, rate |
| **Cost Price** | What the shop paid for a Batch of a Product; the basis for the below-cost guard and margins. | buy rate, wholesale |
| **GST Slab** | The tax rate carried on the Product row (0/5/12/18%), split into equal CGST + SGST intra-state. | tax rate, VAT |
| **HSN Code** | The tax-classification code on each Product, shown per Line on the invoice. | tax code |
| **Round-off** | The bill-level adjustment to the nearest rupee after per-line tax is summed. | rounding, adjustment |
| **Payment Mode** | How a Bill is settled: Cash, UPI, Card, or **Khata** (credit). | tender, method |
| **Finalize** | The single atomic step that turns a Draft Bill into a Bill: oversell check, stock decrement, GST computation, invoice-number mint (and Khata charge if on credit). | close, submit, checkout |

## Credit

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Customer** | A person the shop extends credit to, identified per-shop by display name with optional phone. Distinct from the Owner. | client, buyer |
| **Khata** | A Customer's running credit ledger; one per Customer, its balance the sum of its Khata Entries. | account, tab, credit account |
| **Khata Entry** | A single append-only charge or payment on a Khata, with amount, type, optional Bill reference, and timestamp. | ledger line, txn |

## People & configuration

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Owner** | The single shopkeeper operating the store, identified by Telegram user id; also the key for Preferences and Shop Profile. | user, admin |
| **Preference** | A standing owner setting that persists across chats (default payment, preferred brand); distinct from an in-message override. | setting, config |
| **Shop Profile** | The shop's identity — name, address, GSTIN — printed on every invoice. | store info, org |

## Operations

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Grounding** | The rule that every Product, price, slab, and HSN originates from a database row, never the model. | lookup, resolution |
| **Oversell Guard** | The tool-layer refusal that prevents a Bill from driving stock negative, enforced under a row lock at Finalize. | stock check |
| **FEFO** | First-Expiry-First-Out — the order in which Batches are consumed on a sale. | FIFO, rotation |
| **Daily Close** | A read-only report of the IST business day: total, tax collected, cash vs UPI split, top items. | end of day, cashup |

## Relationships

- A **Bill** is produced by finalizing exactly one **Draft Bill**; a Draft Bill produces at most one Bill.
- A **Draft Bill** and a **Bill** each have one or more **Lines**; every Line references exactly one **Product** by `product_id`.
- A **Product** has one or more **Batches**; its sellable stock is the sum of its non-expired Batches, consumed **FEFO**.
- Every change to a **Batch** quantity appends one **Stock Ledger** row.
- A **Customer** has exactly one **Khata**; a **Khata** is the sum of its **Khata Entries**.
- A **Bill** with Payment Mode = **Khata** writes one charge **Khata Entry** at Finalize.
- An **Owner** has one **Shop Profile** and many **Preferences**, all keyed by Telegram user id.
- An **Alias** points to one or more **Products**; a **Barcode** points to exactly one Product.

## Example dialogue

> **Dev:** "When the owner says 'make a bill: 2kg sugar, 4 Maggi', do we touch stock right away?"

> **Domain expert:** "No — that opens a **Draft Bill** and adds two **Lines**. Stock doesn't move until **Finalize**. Each Line has to carry a grounded `product_id`, so the agent must run **find_product** first — that's **Grounding**; it never invents a **Product** or an **MRP**."

> **Dev:** "And if the owner then says 'drop the butter, make it 6 Maggi'?"

> **Domain expert:** "Still just editing the Draft Bill's Lines. The **Oversell Guard** and GST only run at **Finalize**. If six Maggi exceeds stock, Finalize refuses — the Draft Bill stays open."

> **Dev:** "What if it's on Ramesh's credit instead of UPI?"

> **Domain expert:** "Then Payment Mode is **Khata**, and Finalize does two things in one transaction: decrement the **Batches** FEFO and write a charge **Khata Entry** against Ramesh's **Khata**. His balance is just the sum of his Khata Entries, so it updates immediately."

> **Dev:** "Ramesh vs the shopkeeper — both 'users'?"

> **Domain expert:** "No. The shopkeeper is the **Owner** — the only one on the bot. Ramesh is a **Customer** — he never touches Telegram; we only track his Khata. Don't call either an 'account'."

## Flagged ambiguities

- **"Bill" (open vs finalized).** The conversation used "bill" for both the thing being built and the finished sale. These are distinct: a **Draft Bill** is editable and holds no stock; a **Bill** is immutable and has moved stock and minted an invoice number. Never use "order" or "cart" for either.
- **"SKU" vs "Product".** SKU is the *identifier*; the sellable entity is the **Product**. Use SKU only for the id field, never as a synonym for Product.
- **"user" vs Owner vs Customer.** Three different actors were loosely called "user". The **Owner** is the single shopkeeper (a Telegram user id); a **Customer** is a credit recipient who is *not* on the bot. Reserve "user" for neither — use the precise term.
- **"credit".** Overloaded: as a **Payment Mode** it means "settle via **Khata**"; generically it can mean the outstanding balance. Prefer "Khata" for the ledger and "Payment Mode = Khata" for the settlement.
- **"quantity".** Not a single type — it is an **integer count** for `packaged` **Unit Type** and a **decimal** for `loose`. Never assume integer quantities.
- **"price".** Split deliberately: **MRP** is the tax-inclusive sell price the customer pays; **Cost Price** is what the shop paid (per **Batch**). Don't conflate them — the below-cost guard depends on the distinction.
- **"account".** Avoided entirely — it collapses **Owner**, **Customer**, and **Khata**, which are three separate concepts.
