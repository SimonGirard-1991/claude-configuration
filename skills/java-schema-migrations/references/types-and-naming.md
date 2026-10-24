# Types and naming

The column types, keys, names and privileges that keep later migrations cheap. The facts
were checked on 2026-10-23 and 2026-10-24 on PostgreSQL 18.6, against the manual's
[CREATE TABLE](https://www.postgresql.org/docs/18/sql-createtable.html),
[sequence functions](https://www.postgresql.org/docs/18/functions-sequence.html),
[GRANT](https://www.postgresql.org/docs/18/sql-grant.html),
[REVOKE](https://www.postgresql.org/docs/18/sql-revoke.html) and
[privileges](https://www.postgresql.org/docs/18/ddl-priv.html) pages.
`~/.claude/evals/java-schema-migrations/probes/lock-and-visibility.sh` reruns the `max(id)`
visibility case.

## Contents

- Money and time columns
- Text with a CHECK
- Identity columns
- Naming constraints and indexes
- Privileges for the application role

## Money and time columns

`java-financial-correctness` owns these, and this file does not repeat them:

- `numeric` per kind of value, and a declared scale that rounds silently, pads and
  overflows: its money reference, § Storage in Postgres.
- `timestamptz` for an event, `date` for a civil date, and `::date` following the session's
  zone: its time reference, § Postgres and JDBC.

## Text with a CHECK

- A bounded string is `text` with a named `CHECK`, such as
  `CONSTRAINT shipments_tracking_code_check CHECK (char_length(tracking_code) <= 40)`,
  rather than `varchar(n)`.
  - Changing the `CHECK` is online: add the new one `NOT VALID`, validate it, then drop the
    old one (`online-changes.md` § NOT NULL and CHECK constraints).
  - Shortening a `varchar(n)` rewrote the table under ACCESS EXCLUSIVE. Lengthening it, or
    turning it into `text`, changed the catalog only.
- A closed set of values is `text` with a `CHECK` that lists them, or a reference table
  with a foreign key, rather than an enum type. A value added to an enum could not be used
  in the transaction that added it ("unsafe use of new value"), and a value cannot be
  removed ("dropping an enum value is not implemented").

## Identity columns

- A key the database generates is `bigint GENERATED ALWAYS AS IDENTITY`, under a named
  primary key.
  - The identity generates the values, and the primary key enforces their uniqueness.
    Without one, an `OVERRIDING SYSTEM VALUE` insert stored a second id 1.
  - `bigint` from the start, because `int` to `bigint` later rewrites the table and its
    indexes.
  - `ALWAYS` refuses an explicit value, "cannot insert a non-DEFAULT value into column",
    unless the `INSERT` says `OVERRIDING SYSTEM VALUE`. It refuses an update to anything
    but `DEFAULT`.
  - `BY DEFAULT` accepts an explicit value and leaves the sequence where it was, so the
    next default insert collided with it ("duplicate key value violates unique
    constraint").
  - `COPY` writes the given values even into an `ALWAYS` column and leaves the sequence too:
    after copying id 500, the next insert got id 1. A migration or a load that writes ids
    into a table no other session writes to meanwhile resets the sequence after it:

    ```sql
    SELECT setval(pg_get_serial_sequence('shipments', 'id'), (SELECT max(id) FROM shipments));
    ```

    - `max(id)` cannot see another session's uncommitted inserts, only its own
      transaction's. Run while a writer held id 501 uncommitted, the reset set the sequence
      back to 500, and the next insert collided on 501.
    - `setval` takes effect at once and outlives a rollback: a rolled-back
      `setval(…, 1000)` still made the next id 1001.
    - On an empty table, `max(id)` is NULL, and `setval` returned NULL and changed nothing.

  - The application role needs no privilege on an identity column's sequence. On a
    `serial` column, a role with `INSERT` on the table was refused: "permission denied for
    sequence …_id_seq".
  - Adding an identity column to an existing table rewrites it.
- A key the application generates, such as a UUID, needs no sequence at all, and the
  choice between the two is a design decision. This section covers the database's keys.

## Naming constraints and indexes

- Each migration names the constraints and indexes it creates. A later migration
  validates, drops or replaces them by name, and the name appears in the error a violation
  raises.
- PostgreSQL's own names are `<table>_<columns>_<suffix>`, with `_pkey`, `_key` for a
  unique constraint, `_fkey`, `_check`, `_not_null` (stored in `pg_constraint` since 18)
  and `_idx`. An unnamed name depends on what already exists: a second unnamed check on the
  same column became `_check1`, and a second index `_idx1`.
- A name longer than 63 bytes is cut with only a notice: `identifier "…" will be truncated
  to "…"`. Two long names that share their first 63 bytes then collide.
- A repo keeps one scheme. An existing repo keeps its own, and a new one can take
  PostgreSQL's suffixes.

## Privileges for the application role

- The migration role owns the tables. The application connects as another role that holds
  data privileges only, so it cannot alter or drop what it uses.
- Default privileges grant a new table automatically, but only one created by the role they
  name. After `ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA app GRANT SELECT,
  INSERT, UPDATE, DELETE ON TABLES TO app_user`, `app_user` could read a table `migrator`
  created and was refused one a superuser created. So every migration runs as the
  migration role, a manual fix included.
- The role also needs `USAGE` on the schema. Without it, those default privileges led to
  "permission denied for schema app". `PUBLIC` holds `USAGE` on the `public` schema, and on
  no schema created later.
- Default privileges on tables do not cover sequences, which matters for `serial` and not
  for identity columns (§ Identity columns).
- Privileges add up. A role holds the union of its table-level grants, its column-level
  grants, the grants of every role it inherits from, and `PUBLIC`'s. So a column-level
  grant restricts nothing on its own:
  - On top of the table-wide `UPDATE` the default privileges above grant,
    `GRANT UPDATE (tracking_code)` still let the role update every column. So did a
    table-wide `UPDATE` inherited from a group role.
  - Limiting updates to one column takes a table grant without `UPDATE`, then
    `GRANT UPDATE (tracking_code)`. A `REVOKE UPDATE` on the table also removed the column
    grants. With only the column grant, an update of another column was refused.
- A column added later is covered by a table-level grant: `GRANT SELECT ON` the table let
  the role read it. A column-level grant does not cover it, so a migration that adds a
  column the role must update grants that column in the same migration.
- An append-only table, whose role gets `SELECT` and `INSERT` only:
  `java-financial-correctness`, its ledgers reference.
