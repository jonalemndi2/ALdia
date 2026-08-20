# ALdía

### The open-source business engine built for AI agents.

**ALdía turns an AI assistant into a business operator you can actually trust with money.**

Instead of handing an agent database access, ALdía exposes the business itself —
invoicing, payments, customers, vendors, inventory, checks, expenses, cash — as
**48 permission-controlled MCP tools**, with identity, idempotency, structured
errors and an immutable audit trail already built in.

*[Léeme en español](README.es.md)*

```text
You: "John paid invoice #1842 with this check."   [photo attached]

  Assistant  ── reads it, extracts the data, asks what's missing
      ↓  MCP
  ALdía      ── validates, executes, records
      │        ✓ payment recorded        ✓ check added to the portfolio
      │        ✓ customer balance updated ✓ operation audited
      ↓
  Browser    ── where you see exactly what happened, and fix it if needed
```

The assistant **interprets**. ALdía **validates and executes**. The web console
**supervises**.

No accounting rule lives inside a model's prompt, and the agent never writes SQL.

---

## Why this is different

Most business software is built around forms. ALdía is built around **operations**.

An agent connected to ALdía doesn't get a database. It gets a vocabulary:

```
find_customer            find a customer
get_customer_balance     what they owe, and since when
create_invoice           issue an invoice
record_payment           record a customer payment
record_vendor_payment    pay a vendor
record_expense           record an expense
find_product             check inventory
list_checks              checks in the portfolio
list_debtors             who owes money, and since when
get_audit_log            what happened, and who did it
```

All 48 of them are business actions, not fiscal ones: `create_invoice` means
the same thing in Miami as in Córdoba. What changes underneath is which rules
the server applies.

Every write goes through the **same code path as the web application**: the same
validations, the same transaction, the same audit record. There is no second
implementation to drift out of sync, because the MCP server never touches the
database — it speaks HTTP to the same API your browser does.

## The part nobody builds until it hurts

When an agent starts moving real money, four problems show up. All four are
already solved here, and covered by tests.

**🔁 Idempotency that actually holds**
An agent retries when it doesn't get a response — and a lost response doesn't
mean a lost operation. Send `X-Operation-Id` and the identifier is **reserved
before execution**, not recorded after it. Two simultaneous retries can't both
get through. *(The naive version — check, execute, then save — leaves a window
where both do. We wrote the test that proves it, then closed it.)*

**🧠 Errors an agent can act on**
Every error carries a stable `codigo`, the data that filled it (`params`), and
an `accion` from a closed set of four:

```json
{ "detail": "Not enough stock for 'Coca 2.25': 12 requested, 5 on hand",
  "codigo": "STOCK_INSUFICIENTE",
  "accion": "corregir",
  "params": { "producto": "Coca 2.25", "pedido": 12, "disponible": 5 } }
```

`reintentar` · `corregir` · `preguntar` · `abortar`. A new agent behaves
correctly without knowing the whole catalogue — it just reads that field. The 32
codes are published at `GET /api/errores`, no authentication required, because
an agent getting a `401` needs to be able to look it up.

**🔐 Who asked, and who executed**
An agent can declare which person it's acting for. Permissions are the
**intersection** of the service account and that person — never one or the
other, so a leaked agent credential can't become a universal impersonation key.
Acting on someone's behalf is an explicit permission an administrator grants,
account by account.

**❓ Ambiguity without redoing the work**
*"There are two customers named John Smith. Which one?"* The operation is stored
exactly as it was going to run; confirming it means "execute what you already
described, with this clarification." The agent doesn't rebuild the request and
risk changing something else.

**📋 An audit log that can't be edited**
Every write is recorded automatically by middleware — including the **rejected**
attempts, which are usually the interesting ones. It lives in its own schema, so
it survives a full database wipe, and there is no endpoint to delete or modify
it. Not even for the administrator.

---

## Runs on your machine. No cloud, no subscription.

ALdía is a single Python process and one SQLite file. It installs on the shop's
own PC and the terminals reach it over the local network.

**It works with the internet down.** Nothing is loaded from a CDN — that was a
deliberate fix, not an accident. A store that loses connectivity keeps invoicing.

It also backs itself up: once a day at startup, keeping the last 7, using
SQLite's backup API rather than a file copy — in WAL mode, copying the file
silently loses the day's most recent sales. Each copy is verified with
`integrity_check` on the spot.

## Built for more than one country

Business operations are universal. Tax rules aren't.

ALdía keeps a common engine and swaps **country packs**. One configuration key
changes how identifiers are validated, which tax applies, and whether documents
need approval from an agency.

|                        | 🇦🇷 Argentina | 🇺🇸 United States |
|------------------------|--------------|-------------------|
| Tax ID                 | CUIT, with check digit | EIN, format + assigned prefix |
| Sales tax              | VAT — closed list of legal rates | Sales tax — any plausible rate |
| Document authorization | CAE from ARCA (WSAA + WSFEv1) | none |
| Currency               | ARS | USD |
| Payment methods        | cash, check, transfer, cards | + ACH |
| Vendor records         | — | legal name, DBA, W-9, 1099 worksheet |

> **U.S. sales tax is not a compliance solution, and the system says so itself.**
> It applies **one rate you type in**, to everything. That's correct for a
> single-location business with obligations in one jurisdiction. It does **not**
> determine jurisdiction (state + county + city + special districts), apply
> origin/destination sourcing, track economic nexus, handle exempt categories, or
> manage resale certificates. A specialised tax provider can be plugged in
> without touching the core — the interface is there and tested; no integration
> ships with it. `GET /api/config/pais` returns these limits as `advertencias`
> so an agent can repeat them to the user instead of hiding them.

Adding a country means implementing three questions — how the tax ID validates,
what tax applies, whether documents need authorization — and nothing in the core
changes. Your agent keeps calling the same tools either way.

## Money is not a float

Every amount is stored as **integer cents**, with commercial rounding applied
once, explicitly, at the point of conversion. This isn't pedantry:

```python
sum([0.10] * 10)   # 0.9999999999999999
1234.56 * 0.21     # 259.25759999999997   ← the VAT on a real invoice
```

Balances, ledger entries and period totals reconcile to the cent, permanently.
Invoice numbering comes from a sequence table, not `max + 1`, so voiding a
document never causes its number to be reused.

## Quick start

Requires **Python 3.10+**. On the machine that will act as the server:

```bash
git clone https://github.com/jonalemndi2/ALdia.git
cd ALdia
instalar.bat        # Windows — creates the venv and installs dependencies
iniciar_web.bat     # starts the server
```

Then open `http://localhost:8000`. First login is `admin` / `admin123`, and the
system **refuses to let you operate until you change it** — that password is
published in this file, so an installation that keeps it has a known way in.

To connect an assistant, see [`mcp/README.md`](mcp/README.md). Give it a
**limited-role account**, not the administrator's: a connected agent can create
documents and move real money.

## Before exposing it to the internet

**HTTPS is mandatory.** Without a certificate, credentials and session tokens
travel in plaintext. Use a reverse proxy — [Caddy](https://caddyserver.com/)
handles it in a few lines.

And declare your proxy: `ALDIA_PROXIES=127.0.0.1`. Without it the server sees
every request as coming from the proxy, and eight failed logins are enough to
lock out the entire store.

## Honest limits

- Anyone with filesystem access to `backend/aldia.db` can edit it outside the
  application. There, the protection is OS permissions and backups.
- The audit log records writes, not reads.
- One installation, one business. There is no multi-tenancy, by design.
- U.S. sales tax: see the warning above.
- No 1099 forms are generated — only a worksheet. Thresholds, exclusions and
  deadlines change every year, and a return filed wrong is worse than none.

## Verified

**236 tests** covering amount exactness, authentication and per-role
permissions, fiscal validation, idempotency under real concurrency, automatic
backup, and the full commercial cycle with its reversals. They run on every push
against Python 3.10 and 3.13, plus once more with the exact pinned versions
recommended for production, plus a job that fails if a secret or a database ever
gets committed.

## Documentation

| | |
|---|---|
| [`docs/AGENTES.md`](docs/AGENTES.md) | What agents can do, and what must not be broken |
| [`docs/CONVERSATIONAL-COMMERCE.md`](docs/CONVERSATIONAL-COMMERCE.md) | **Not built yet** — an open design for autonomous selling, and where to start |
| [`docs/INTERNACIONALIZACION.md`](docs/INTERNACIONALIZACION.md) | How country packs work; what's done and what isn't |
| [`docs/AFIP.md`](docs/AFIP.md) | Argentine electronic invoicing setup |
| [`mcp/README.md`](mcp/README.md) | Installing and connecting the MCP server |
| [`skills/`](skills/) | Task playbooks for the assistant, per country |
| [`SECURITY.md`](SECURITY.md) · [`CONTRIBUTING.md`](CONTRIBUTING.md) | Reporting a vulnerability · contributing |

## Built with

ALdía was designed and written with AI coding assistants, and it is built to be
operated by them. Both halves of that sentence are the point.

**Written with** — [Claude Code](https://claude.com/claude-code), OpenAI Codex,
Google Gemini, DeepSeek, in [Visual Studio Code](https://code.visualstudio.com/).

**Built to be driven by** — any [MCP](https://modelcontextprotocol.io/) client.
[OpenClaw](https://github.com/openclaw) is the assistant this engine was shaped
around, but nothing here depends on it: the 48 tools are plain MCP, and the
server never assumes which client is on the other end.

That's deliberate. An engine that only works with one assistant isn't
infrastructure — it's a plugin.

## License

**Apache License 2.0** — see [LICENSE](LICENSE).

Use it, fork it, build a product on it, ship it commercially. No copyleft
obligation: you are not required to publish your changes. The license includes
an explicit patent grant, which matters for software that computes taxes.

If you build something with it, I'd genuinely like to hear about it.

## Who made this

Built by **Jonathan Alemandi** ([@jonalemndi2](https://github.com/jonalemndi2)).

It started as a replacement for a VB6 + Access system running a real shop in
Villa Huidobro, Córdoba, and turned into an attempt to answer a harder question:
what does a business system need before it is safe to let an AI agent operate it
with real money?

Most of the interesting decisions here are defensive, and the reasoning behind
them is written into the code rather than lost in a commit message — see
[`backend/dinero.py`](backend/dinero.py) on why money is never a float,
[`backend/database.py`](backend/database.py) on why writes take the lock up
front, or [`backend/idempotencia.py`](backend/idempotencia.py) on why checking
before writing leaves a hole big enough to bill someone twice.

Issues and pull requests welcome.
