---
name: java-financial-correctness
description: >-
  Use when writing or reviewing Java code that computes, rounds, converts, allocates,
  stores or sends money, or that decides business dates, cutoffs and scheduled business
  jobs, or that books, reconciles or imports ledger entries. Covers a rounding policy per
  operation, currency minor units, rates and prices at their own precision, BigDecimal
  and java.time traps, Postgres NUMERIC and timestamptz, append-only double-entry
  postings, reconciliation breaks and idempotent statement import. Skip for non-Java code.
---

# Java financial correctness

This skill holds the rules for Java code whose numbers must be right to the last minor
unit: amounts and their rounding, the dates and times that business rules hang on, and
ledgers that someone else reconciles against. It states policy and verified facts. The
business still owns each rounding mode, cutoff and calendar, and the code records each
decision with its source.

Defaults: Java 25 (`BigDecimal`, `java.time`), Spring Framework 7, PostgreSQL 18 with
pgjdbc, and Jackson 3. Each reference names the versions its facts were checked on.

## When to use

- Code that computes, rounds, converts, allocates, stores or sends money: fees, interest,
  FX, valuations, payouts, invoices, settlement amounts.
- Code that decides a business date or time: value and booking dates, cutoffs, statement
  periods, and scheduled jobs that do business work.
- A ledger: postings, balances, positions, corrections, reconciliation, statement import.
- Reviewing any of these, including a diff that only touches one rounding call or one
  `@Scheduled` cron.

## When NOT to use

- Non-Java code. The Python and frontend conventions carry their own money and date rules.
- Java with no money, booking or business-date logic.
- Statistics and analytics in `double`, where the code says so and nothing is posted from
  them.

## Core principles

1. **Each kind of value keeps its own precision.** A posted amount takes the currency's
   minor units. An intermediate value, a unit price, a quantity and an FX rate keep their
   own precision and never take a currency's scale.
2. **One rounding policy, per business operation.** A table in code gives each operation
   its mode, and the operation names the boundary where it rounds. Every rounding goes
   through it, and each mode records where it comes from.
3. **Round once, at the boundary, after the arithmetic.** Never round before a
   multiplication, and never round a rate to a currency's scale.
4. **The minor unit comes from the currency**, never from a constant 2. A cash step such
   as CHF 0.05 is a function of its own, not a scale.
5. **Intermediate values compute in one stated `MathContext`.**
6. **An amount crosses JSON as a decimal string**, with its currency beside it.
7. **Events are `Instant`s, civil dates are `LocalDate`s, and every zone is named**: when
   the `Clock` gives a business date, in a cron, and in SQL.
8. **Postings are append-only and balance in each currency.** A correction is a reversal,
   and a balance is derived from postings.
9. **Reconciliation makes every difference an explicit break.** An import is idempotent
   and notices a line re-sent with different content.

## Reference map

Open a reference when you implement one of these, or when judging one in review needs its
detail.

| I need to… | Open | Contains |
|---|---|---|
| Choose a scale, round, convert, allocate, store or send an amount | `references/money.md` | Kinds of value, the policy table, minor units, cash steps, intermediates, allocation, `BigDecimal` traps, Postgres `numeric`, JSON |
| Decide a business date, a cutoff or a job's schedule | `references/time.md` | Which type, explicit zones, DST in Java and Postgres, cutoffs, `@Scheduled`, business calendars, `timestamptz` over JDBC |
| Design or review postings, balances, reconciliation or a statement import | `references/ledgers-and-reconciliation.md` | Immutability, double entry, derived balances and checkpoints, breaks, idempotent import |

## Review checklist

- [ ] Every rounding call goes through the policy, and the policy covers its operation. A
  mode outside the policy, or one that contradicts it, is a finding. A mode that matches a
  documented counterparty or regulatory rule is not.
- [ ] No rate, price, quantity or intermediate value is rounded to a currency's scale, and
  nothing is rounded before a multiplication.
- [ ] The minor units come from `Currency`, or from the policy for a pseudo-currency. A
  cash step uses its own function.
- [ ] Every `divide` and `pow` passes the stated `MathContext` or an explicit scale that the
  policy names.
- [ ] Amounts are compared with `compareTo` or `signum`, and none is built from a `double`.
- [ ] Each column holds what the policy writes without rounding it, and a read normalises
  the scale.
- [ ] JSON carries amounts as plain decimal strings with their currency.
- [ ] Business dates come from the injected `Clock` and a named zone. A `@Scheduled` cron
  names its zone, and a daily job either avoids the DST hours or is keyed on its business
  date under a unique constraint.
- [ ] Postings are never updated or deleted, entries balance in each currency, and
  corrections are reversals.
- [ ] A statement import has a natural key per line and detects a changed re-send.
  Differences become breaks.

## Cross-references

- Idempotency keys, inbox tables and at-least-once delivery: `java-reliability-messaging`.
- Value objects, aggregates and where a ledger's invariants live: `hexagonal-ddd-java`.
- Where `Money` sits in a hexagonal module: `hexagonal-module-bootstrap`'s aggregate
  template. Its minimal `Money` accepts fewer decimals than the currency's. A ledger's
  `Money` takes exactly the currency's minor units, which the allocation in
  `references/money.md` relies on.
- Tests for these rules (a fixed `Clock`, boundary cases, Postgres in Testcontainers):
  `java-testing-strategy`.
