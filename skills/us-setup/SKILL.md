---
name: us-setup
description: Configure an ALdia installation to run in the United States - set the country, currency, language, the business EIN and the manual sales tax rate, and verify what the system will and will not do. Use when the user says "set up ALdia for the US", "we're in Florida", "switch to dollars", "configure sales tax", "our EIN is", "this is a US business", or when get_country_rules() reports a country that does not match where the business actually operates.
---

# US setup (ALdia)

ALdia runs the same engine everywhere; the country is a property of the
**installation**, not of each transaction. Switching it changes how every
identifier is validated, which tax applies, and whether invoices need approval
from a tax agency.

## Step 0 — What is it set to now?

```
get_country_rules()
```

If `codigo` is already `US`, skip to step 3. If it says `AR`, the installation
is validating CUITs and expecting an ARCA authorization code for every invoice —
neither of which exists in the United States.

## Step 1 — Switch the country

The country lives in the business configuration. Setting it to `US` changes, in
one move:

| | Before (`AR`) | After (`US`) |
|---|---|---|
| Tax ID | CUIT, 11 digits, check digit | EIN, 9 digits, `XX-XXXXXXX` |
| Sales tax | VAT, closed list of legal rates | Sales tax, any plausible rate |
| Invoice approval | CAE from ARCA | none |
| Currency | ARS | USD |
| Region label | Provincia | State |

Language follows the country automatically unless someone set it explicitly.

**Do this once, before loading data.** Customers already on file keep the tax ID
they were created with; the system will not reinterpret them.

## Step 2 — Set the sales tax rate

This is the part that needs the most care, so read it to the user rather than
deciding for them.

ALdia applies **one rate that you type in**, to everything. That is correct only
if the business:

- has a single location,
- sells in person, and
- has tax obligations (nexus) in one jurisdiction only.

**It does not** figure out the jurisdiction (state + county + city + special
districts), apply origin-versus-destination sourcing rules, track economic
nexus in other states, handle exempt categories such as groceries, clothing or
medicine, or manage resale exemption certificates.

Ask the user for the combined rate their accountant gave them. If they do not
know it, **say so and stop** — do not guess a rate off the top of your head. A
plausible wrong rate is worse than an empty field, because nobody notices it.

## Step 3 — The business's own details

Load the business EIN, legal name and address into the configuration. The EIN
has no check digit: unlike a CUIT, there is no way to tell offline whether it is
real. ALdia checks the format and that the prefix is one the IRS has assigned,
and nothing more. Say that to the user so they double-check the number.

## Step 4 — Confirm what changed

```
get_country_rules()
```

Read back to the user: the tax ID name, the tax name, the currency, and **every
line of `advertencias`**. Those are the known limits of what the system does.
Telling someone their sales tax is handled, when it is one flat manual rate,
sets them up to file wrong.

## What this skill does not do

- It does not give tax advice. Rates, nexus and exemptions are questions for an
  accountant.
- It does not file anything with any agency.
- It does not migrate existing Argentine data to US rules. Records keep the
  identifiers they were created with.
