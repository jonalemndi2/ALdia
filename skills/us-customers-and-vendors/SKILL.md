---
name: us-customers-and-vendors
description: Add and maintain customers and vendors in a US ALdia installation - EIN instead of CUIT, legal name versus DBA, W-9 tracking, 1099 eligibility, and US addresses. Use when the user says "add a customer", "new vendor", "their EIN is", "we got their W-9", "they do business as", "1099 vendor", or when a tax ID is rejected and you need to know what the installation expects.
---

# Customers and vendors (US)

Run `ver_reglas_del_pais()` first if you have not already. Everything below
assumes it reported `codigo: US`.

## Adding a customer

```
alta_cliente(tax_id="12-3456789", nombre="Acme Plumbing LLC",
             city="Miami", region="FL", postal_code="33101")
```

`tax_id` and `cuit` are the same parameter — send the number you were given and
the server validates it with the rules of the installation. Same for
`city` / `region` / `postal_code`, which in the Argentine naming were
`localidad` / `provincia` / `cp`.

**About the EIN.** Nine digits, written `XX-XXXXXXX`. Unlike a CUIT it has **no
check digit**: there is no way to verify offline that it belongs to anyone. The
system checks the format and that the prefix is one the IRS has assigned. If a
number passes, that means it is well formed — not that it is real. When a user
dictates one, read it back.

If the customer is an individual rather than a business, do not invent an
identifier. Ask. SSNs and ITINs are sensitive and this installation does not
handle them.

## Adding a vendor

```
alta_proveedor(tax_id="12-3456789", nombre="Acme Supply",
               legal_name="Acme Supply Company LLC", dba="Acme Supply",
               city="Miami", region="FL", postal_code="33101")
```

Four fields exist only for the US:

| Field | What it is |
|---|---|
| `legal_name` | The exact registered name. This is what goes on an information return, and it is often not what people call the company. |
| `dba` | "Doing business as" — the trading name. |
| `w9_recibido` | Whether the vendor's Form W-9 is on file. |
| `elegible_1099` | Whether this vendor belongs in the 1099 worksheet. |

### Never set `elegible_1099` without the W-9

Marking a vendor eligible is asserting that they belong in an information
return. Doing that without the form on file is inventing a filing on someone
else's behalf.

The correct order is: get the W-9 → record `w9_recibido=true` with its date →
then mark `elegible_1099=true` **if the user says so**. If the user asks you to
mark a vendor eligible and there is no W-9, say what is missing and ask them to
confirm rather than doing it silently.

You are also not the one who decides eligibility. Whether a vendor gets a 1099
depends on what they were paid for, how they are organized, and thresholds that
change every year. Record what the user tells you; do not infer it.

## Fixing a tax ID that was typed wrong

This used to be impossible and now is not. If a customer or vendor was created
with the wrong number and already has invoices or payments, the record can be
corrected — the change follows through to every document.

The system will refuse the first attempt and tell you **how many documents it
would affect**. That refusal is deliberate: it is a tax identifier on documents
already issued, so the user has to confirm it, not you. Show them what will be
affected, get an explicit yes, and only then repeat the call with the
confirmation.

Do not use this to replace one company with another. It is for correcting a
typo on the same company.

## Addresses

Use `city`, `region` (the state — two letters), `postal_code` and let the
country default. The older `localidad` / `provincia` / `cp` parameters still
work and write the same data, so nothing breaks if you use them; prefer the new
names.

## What this skill does not do

- It does not verify an EIN against the IRS. Nothing offline can.
- It does not decide 1099 eligibility.
- It does not handle SSNs or ITINs.
