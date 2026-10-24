---
name: java-schema-migrations
description: >-
  Load before planning, writing or reviewing any Flyway migration in a Java service on
  PostgreSQL, including recovering a failed migration, flyway repair, and setting up jOOQ
  code generation from the migrations. Covers new columns, indexes and constraints, NOT
  NULL, type changes, backfills and renames, migration locations, column types, identity
  keys, naming and grants, each judged by its lock, the table's size and write rate, the
  deployment and the availability target. Skip for non-Java code or other databases.
---

# Java schema migrations

This skill holds the rules for changing a PostgreSQL schema through Flyway in a Java
service. It states policy and verified facts. Whether a change needs its online form
depends on its context: the same `CREATE INDEX` is an outage on a busy table under rolling
deploys and correct on a small one released in a maintenance window.

Defaults: PostgreSQL 18, Flyway 13 (Spring Boot 4.1 manages 12.4), jOOQ 3.21 and
Testcontainers 2. Each reference names the versions its facts were checked on.

## When to use

- Writing a migration: a table, a column, an index or a constraint, a type change, a
  backfill, a rename or a drop.
- Choosing a column type, a key, a constraint name or the application role's privileges.
- A failed migration, a checksum mismatch, `repair`, migration locations across modules,
  or a version merged out of order.
- Generating jOOQ code from the migrations, or testing a migration against the previous
  schema's data.
- Reviewing any of these, a diff that adds one `V…sql` file included.

## When NOT to use

- Non-Java code, or a database other than PostgreSQL.
- Deciding whether a query needs an index at all: that is `java-performance-patterns`,
  from an execution plan. This skill covers how the index is then built.

## Core principles

1. **Judge a change by its context.** The lock it takes, the table's size and write rate,
   the deployment and the availability target decide whether it needs its online form. A
   migration without `CONCURRENTLY` or `NOT VALID` is not a defect in itself.
2. **The repo states that context.** A review reads it from the README, an ADR or the
   deploy configuration. When it is missing, the review asks for it, or, where it cannot
   ask, reports the finding conditionally.
3. **DDL on a busy table runs under a short `lock_timeout`, set before each migration.**
   Even a catalog-only change stops the traffic queued behind it while it waits for its
   lock. A concurrent build's waits block no reads or writes, so its timeout is chosen for
   the writers and snapshots it may wait for.
4. **A busy table under rolling deploys takes the online forms:** concurrent index builds,
   `NOT VALID` then `VALIDATE`, batched backfills, and expand and contract across releases.
   On a small table, or with nothing running during the change, the direct forms are right.
5. **A concurrent build gets a migration of its own, Flyway's session lock and a
   `lock_timeout` chosen for the writers and snapshots it may wait for**, and it drops an
   invalid leftover before it builds. A build that can outlast the application's startup
   runs outside the application.
6. **A non-transactional migration that fails needs a repair**, and what it left behind is
   cleaned up before the next deploy.
7. **All locations share one version sequence**, and a migration others have run is
   edited only to fix one that failed.
8. **Generated code comes from the migrations**, applied by Flyway to a real PostgreSQL.
9. **A migration that moves data is tested from the previous schema with its data.**
10. **Keys the database generates are `bigint` identity columns under a named primary key,
    bounded strings are `text` with a named `CHECK`, every constraint and index is named,
    and the application role holds data privileges only.**

## Reference map

Open a reference when you write one of these, or when judging one in review needs its
detail.

| I need to… | Open | Contains |
|---|---|---|
| Decide whether a change needs its online form, or write that form | `references/online-changes.md` | Judging by context, the lock and rewrite of each statement, the lock queue and `lock_timeout`, concurrent index builds, `NOT VALID` and `VALIDATE`, foreign keys, batched backfills, expand and contract |
| Run, recover or test migrations with Flyway | `references/flyway-mechanics.md` | Non-transactional migrations, Flyway's advisory lock per runner, session settings, failure and `repair`, locations, jOOQ codegen, migration tests |
| Choose a column type, a key, a name or a grant | `references/types-and-naming.md` | Pointers for money and time columns, `text` with a `CHECK`, identity columns, naming, the application role's privileges |

## Review checklist

- [ ] The context is known: the table's size and write rate, the deployment and the
  availability target. A finding about a lock cites it.
- [ ] Where a large, busy table takes traffic during the migration, no plain
  `CREATE INDEX`, `ADD CONSTRAINT … UNIQUE` or `PRIMARY KEY`, direct `SET NOT NULL`,
  `CHECK` or foreign key without `NOT VALID`, rewriting `ADD COLUMN` or type change, or
  one-statement backfill holds its lock until its migration commits. On a small table or
  in a window, these are fine.
- [ ] DDL on a busy table runs under a short `lock_timeout` set before each migration, a
  concurrent build under one chosen for the writers and snapshots it may wait for, and the
  deploy retries a migration that times out. Nothing the run sets stays on the application's
  connection pool.
- [ ] A concurrent build has a migration of its own, with only the drop of its leftover
  beside it, plus a `SET lock_timeout` and a `.sql.conf` that turns the transaction off
  where it sets its own timeout. It runs with Flyway's transactional lock turned off and
  `client_connection_check_interval` set, and does not rely on `IF NOT EXISTS`.
- [ ] A NOT NULL or `CHECK` added `NOT VALID` over rows that still violate it comes after
  every running writer fills the column and the backfill has finished. A later migration,
  not the same transaction, validates it.
- [ ] A backfill batch walks a range of the key and keeps its filter in its own `WHERE`.
- [ ] Under rolling deploys, each migration works with the previous release's code.
- [ ] No shared migration is edited, except to fix one that failed, and no version
  appears in two locations.
- [ ] New keys the database generates are `bigint` identity columns under a named primary
  key, new constraints and indexes are named, and the application role can do what the
  code needs and no more.
- [ ] jOOQ's generated code matches the migrations, and a migration that moves data has a
  test that starts from the previous schema.

## Cross-references

- Fixing an unshared migration in place, stacking fixes on shared history, and what
  `repair` does: the Migrations bullet of `~/.claude/conventions/java.md` § Stack.
  `references/flyway-mechanics.md` adds what PostgreSQL leaves behind.
- Whether an index pays for itself, from an execution plan: `java-performance-patterns`.
- Repository and migration tests on Testcontainers, never H2: `java-testing-strategy`.
- `numeric` and `timestamptz` columns, and append-only postings with their grants:
  `java-financial-correctness`.
- Where the migrations and the jOOQ adapter sit in a module:
  `hexagonal-module-bootstrap` → `references/db-adapter-jooq.md`.
