---
name: us-sales-tax-and-1099
description: Sales tax and vendor 1099 preparation in a US ALdia installation - how the tax rate is applied and what it does not cover, and how to pull the year-end worksheet of what each eligible vendor was paid. Use when the user says "sales tax", "tax rate", "1099", "year end", "what did we pay this vendor", "getting ready for taxes", "send this to the accountant", or asks whether the system handles their tax filing.
---

# Sales tax and 1099 (US)

This skill is mostly about **what the system does not do**. Say those parts out
loud. Someone who believes their filings are handled, when they are not, finds
out at the worst possible time.

## Sales tax: one manual rate

ALdia applies a single rate that the business typed into its configuration, to
everything it sells. `get_country_rules()` returns it along with
`advertencias`.

That is correct for a business with **one location, selling in person, with tax
obligations in one jurisdiction**. For anyone else it is wrong, and here is
specifically what is missing:

- **Jurisdiction.** A US rate is state plus county plus city plus, sometimes,
  special districts. There are on the order of 13,000 combinations and they
  change.
- **Sourcing.** Depending on the state, the rate that applies is the one where
  the goods ship from, or the one where they arrive.
- **Economic nexus.** Selling above a threshold into another state creates an
  obligation to collect and remit there, with no physical presence needed.
- **Exempt categories.** Groceries, clothing and medicine are taxed differently
  by state.
- **Resale exemption certificates** from wholesale customers.

If the user asks whether ALdia handles their sales tax, the honest answer is:
it applies the rate you gave it, and it does not determine which rate is
correct. A specialised tax service can be connected to do that properly; until
one is, the number is only as good as what was typed in.

**Never invent a rate.** If nobody knows it, that is a question for their
accountant, and saying so is more useful than a plausible guess.

## Year-end 1099 worksheet

```
GET /api/proveedores/informe-1099?anio=2026
```

This gives, for each vendor marked eligible, how much they were paid that year,
their legal name, tax ID, address and whether their W-9 is on file.

### It is a worksheet, not a filing

It exists so the person doing the taxes does not have to add up payments by
hand. **It is not a Form 1099 and does not replace one.** The return is prepared
and filed by an accountant.

The response includes `advertencias` listing what the system cannot know. Repeat
them to the user; do not summarise them away:

- ALdia records **amounts, not tax categories**. It cannot tell a payment for
  services (reportable) from one for goods (generally not).
- It does not know whether the vendor is a corporation, which is usually
  excluded.
- It does not account for withholding.
- It does not see payments made outside the system — cash, a personal card, a
  bank transfer nobody entered.

### Vendors missing a W-9

They appear in the worksheet, flagged, and are also listed under `sin_w9`.
That is on purpose: a missing form is exactly what the user needs to see before
year end, not something to filter out of the report.

Tell them which vendors need a W-9 requested, and how much each was paid, so
they can prioritise.

## Handing it to the accountant

When the user asks for something to send along, give them the worksheet
contents **with the warnings attached**. A list of vendors and amounts, stripped
of the caveats, reads like a finished filing. It is not one.

## What this skill does not do

- It does not compute correct sales tax by jurisdiction.
- It does not generate, print or file any 1099.
- It does not decide which vendors are reportable.
- It does not give tax advice.
