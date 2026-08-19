# Conversational commerce — a direction, not a feature

> **Nothing in this document is built yet.** It's an open design, published so
> someone can pick it up. If you're looking for what ALdía does today, the
> [README](../README.md) describes only shipped behaviour.

## The idea

Today an agent connected to ALdía can operate the business *for its owner*:
issue invoices, record payments, check inventory. The next step is letting it
sell *to a customer*, end to end, in natural language:

```text
Customer: "I need a 24-inch monitor."
Agent:    "I have three in stock…"
Customer: "I'll take the Samsung."

  → stock reserved
  → order created
  → payment requested
  → invoice issued
  → shipment created, tracking returned
```

The architectural rule is the same one the project already follows:

**The agent converses. ALdía decides and executes.**

A conversational layer must never write to the database. It calls MCP tools,
and every business rule stays on the server — including the ones that decide
whether a sale is allowed at all.

## Why this is closer than it looks

A surprising amount of the hard infrastructure already exists, because it was
built for a different reason: letting an agent move money safely.

| What autonomous selling needs | Status | Where |
|---|---|---|
| Retries that don't duplicate an order or a payment | **built** | `backend/idempotencia.py` — the operation id is reserved *before* execution, on every write, via middleware |
| Knowing which customer asked and which agent executed | **built** | `backend/auditoria.py` records actor type, channel, agent and requester |
| Resolving ambiguity without rebuilding the request | **built** | `backend/pendientes.py` — the operation is stored as it was going to run |
| Errors an agent can act on | **built** | `backend/errores.py` — stable code, `params`, and one of four actions |
| Pluggable external providers that never block a sale | **pattern exists** | `backend/impuestos.py` — copy this shape for shipping and payments |
| Concurrency safe enough to sell the last unit once | **foundation exists** | `BEGIN IMMEDIATE` + WAL in `backend/database.py` |

So the work isn't "build an agent platform." It's four domain pieces on top of
one that already holds.

## What's actually missing

### 1. A richer catalogue — start here

`StockMercaderia` has seven fields: code, name, quantity, unit, sale price, tax
rate, cost. There is no brand, category, description, attributes, images,
weight or dimensions.

`search_products("24 inch monitor")` cannot work against that — there's nothing
to match on but a name. **This blocks everything downstream and is the cheapest
piece to build.**

Attributes should be extensible rather than one column per product category:

```json
{ "screen_size": "24", "resolution": "1920x1080", "panel": "IPS" }
```

### 2. Available stock vs. stock on hand — the risky one

Today stock is a single column, decremented directly:

```python
producto.cantidad = disponible - cantidad     # routers/facturas.py
```

Introducing reservations means:

```text
stock_available = stock_on_hand - stock_reserved
```

…which **changes the meaning of `cantidad` for everything that reads it** —
invoicing, delivery notes, the dashboard, the MCP tools, the skills. That's a
semantic migration, not a new table, and it deserves its own pull request with
nothing else in it.

Also: `cantidad` is a float, because a shop sells kilos and litres. Reservations
have to work on fractional quantities.

The concurrency itself is the *easy* part here — the infrastructure already
serialises writes. The test for "two customers buy the last unit at the same
instant" can be written with the same threading pattern as
`tests/test_idempotencia.py::TestCarrera`, which already works.

### 3. Orders

`Remito` (delivery note) + `Venta` (line items) is already an order in embryo —
`Venta` even freezes the unit price per line, which is exactly what an order
needs.

**But a delivery note is a fiscal document.** An order can sit in
`AWAITING_PAYMENT` without anything having left the warehouse. Overloading a
document that has legal meaning with e-commerce states is how you end up with
delivery notes for goods that were never delivered.

**Open question** — see below.

### 4. Payment intents and shipping

Both follow the provider pattern in `backend/impuestos.py`: an interface, a
manual fallback, and the rule that a failing external service never stops the
business from operating. Neither should ship with a real integration written
blind — an integration nobody has run against a real account is not a feature.

## Open design decisions

These are genuinely undecided. If you want to work on this, these are worth
agreeing on first, because they change everything downstream.

**1. New `Order` entity, or extend `Remito`?**
A new entity keeps the fiscal document clean, at the cost of another table and a
mapping when the order ships. Extending reuses working code, at the cost of a
delivery note that can be "awaiting payment."

**2. Does ALdía stay offline-first?**
The project's stated value is that it runs on the shop's own machine and keeps
working with the internet down. Payment gateways and carrier APIs are
inherently online. They can be optional and degrade gracefully — but somebody
has to decide whether the happy path assumes connectivity, because the answer
shapes the whole domain.

**3. Should the 32 error codes move to English?**
They're currently Spanish (`STOCK_INSUFICIENTE`). The repository is now
English-facing. The codes are a published contract, so renaming gets more
expensive over time — and cheaper now than it will ever be again.

## A suggested order of work

Small, independently mergeable pull requests. Roughly:

1. **Catalogue fields** — SKU, brand, category, description, extensible
   attributes, images, dimensions, active flag. Plus a migration. No risk,
   unblocks everything.
2. **`stock_available`** — introduce the concept and update every reader,
   *without* reservations yet. This is the semantic change; isolate it.
3. **`StockReservation`** — with expiry, release, and the concurrency tests.
4. **`Order` + `OrderItem`** — with a state machine the server enforces. Invalid
   transitions must fail; the agent doesn't get to invent states.
5. **Commerce MCP tools** — `search_products`, `create_order`, `reserve_stock`,
   `get_order`, `cancel_order`.
6. **`PaymentIntent`** — abstraction plus a manual provider. Real gateways later.
7. **Invoice from order** — reusing the existing fiscal logic and country packs.
8. **Shipping** — address, quote, shipment, provider interface, mock provider.

The conversational layer belongs in a **separate repository** that consumes MCP.
It shouldn't start until the domain above holds on its own.

## Tests that would have to pass

The interesting ones aren't the happy path:

- Two customers buy the last unit simultaneously — exactly one succeeds.
- A reservation expires and the stock comes back.
- A consumed reservation can't be reused.
- Retrying create-order / payment / invoice / shipment duplicates nothing.
- Cancelling an order releases its stock; paying for one doesn't lose it.
- An invalid state transition is rejected.
- A failing shipping or payment provider doesn't block the sale.

## What should stay out

Not because it's uninteresting, but because it competes with getting one
complete sale right: autonomous discounting, CRM, campaigns, ML
recommendations, marketplace and multi-vendor, route optimisation, complex
returns.

---

**Interested?** Open an issue describing which piece you'd take. The three open
decisions above are the most useful thing to weigh in on, and they cost nothing
to discuss before any code exists.

See [`docs/AGENTES.md`](AGENTES.md) for the properties this project won't trade
away, whatever gets built on top.
