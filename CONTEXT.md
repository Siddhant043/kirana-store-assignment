# Supermarket Ops Agent

A conversational agent that runs an Indian kirana / supermarket store end-to-end from Telegram. The owner operates the shop in plain language; the model orchestrates thin tools that enforce the store's business rules and keep its books consistent.

## Language

**Product**:
A stocked item the shop sells, carrying its own cost price, MRP, quantity, reorder level, GST slab and HSN code. Real SKUs (Aashirvaad Atta 5kg) and loose items (sugar by the kg) are both Products.
_Avoid_: SKU (use for the identifier only), item

**Draft Bill**:
An in-progress bill being built over several messages. Persisted, editable, and has status `open`. Holds no stock — stock is only touched when it becomes a Bill.
_Avoid_: cart, pending order

**Bill**:
A finalized sale. Created by finalizing a Draft Bill: stock is decremented, an invoice number is minted, and it becomes immutable. The source of truth for invoices and analytics.
_Avoid_: order, transaction, receipt

**Line**:
A single product entry on a Draft Bill or Bill — a grounded `product_id`, a quantity, and the derived tax breakup. Never a free-text name.

**Customer**:
A person the shop extends credit to, identified per-shop by a display name with an optional phone number as disambiguator. Distinct from the Owner. Created on first credit, one Khata each.
_Avoid_: client, buyer

**Khata**:
A Customer's running credit ledger. Customers buy on credit and settle later. One per Customer; its balance is the sum of its Khata Entries.
_Avoid_: account, tab, credit account

**Khata Entry**:
A single append-only row on a Khata — a charge or a payment, with amount, type, optional reference to a Bill, and timestamp. The audit trail behind a Khata balance.

**Batch**:
A single intake of a Product held as its own row: a quantity, the cost price paid for it, and an optional expiry date. A Product's sellable stock is the sum of its non-expired Batches. Sales consume Batches First-Expiry-First-Out (earliest expiry first). Loose or non-perishable items use a null-expiry Batch.
_Avoid_: lot, consignment

**Stock Ledger**:
An append-only record of every change to Batch quantities — sale, stock-in, or adjustment — each row carrying the delta, reason, reference (Bill/Draft/Batch) and resulting balance. The audit trail and the source for stock-velocity analytics.

**Preference**:
A standing owner setting that persists across chats and outside the conversation (default payment = UPI, default atta = Aashirvaad 5kg). Distinct from an in-message override, which applies to one bill only.

**Shop Profile**:
The owner's shop identity — name, address, GSTIN — printed on every invoice. Persists across chats.

**MRP**:
The tax-inclusive maximum retail price the customer pays. Taxable value and GST are derived *out of* the MRP, never added on top.
_Avoid_: sell price (when it implies pre-tax), rate

**GST Slab**:
The tax rate carried by a Product (0% loose staples, 5% packaged staples, 12–18% FMCG). Grounded on the Product row, never inferred by the model. Split into equal CGST + SGST on an intra-state bill.

**HSN Code**:
The tax classification code carried by each Product and shown per-line on the invoice.

**Unit Type**:
Whether a Product is `packaged` (sold as whole pieces/packets — Maggi, Aashirvaad Atta 5kg; quantity is an integer count, price = MRP × count) or `loose` (sold by weight/volume — sugar, rice, dal; quantity is a decimal in a base unit of kg or litre, price = per-unit rate × quantity). Loose staples are typically 0% GST. Sub-units the owner speaks in (g, ml) are converted to the base unit before pricing and stock changes.
_Avoid_: bulk, packaged good

**Reorder Level**:
The quantity threshold below which a Product is "running out" and surfaces in low-stock queries.

**Round-off**:
The bill-level adjustment (to the nearest rupee) applied after per-line tax is summed, shown as its own invoice line.

**Owner**:
The single shopkeeper operating the store, identified by their Telegram user id. Also the key for that shop's Preferences and Shop Profile.
_Avoid_: user, admin
