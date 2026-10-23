# Ledgers and reconciliation

How a ledger that someone else relies on stays correct: a client's statement, a
regulator's report, a counterparty's settlement. The Postgres facts were checked on
2026-10-23 on PostgreSQL 18.6.

## Contents

- Postings are immutable
- Double entry
- Balances and positions are derived
- Reconciliation
- Idempotent statement import

## Postings are immutable

- A posting is never updated or deleted. A wrong posting is corrected by a reversal, the
  same postings with their signs flipped and a reference to the original, followed by a
  new, correct entry. The history then shows what was believed, and when.
- The database enforces it, not only the application. The application's role gets
  `SELECT` and `INSERT` on the postings table and nothing else: that role's `UPDATE` and
  `TRUNCATE` both failed with `permission denied for table posting`. A trigger also stops
  the owner's plain `UPDATE`, but not a deliberate one: the owner ran
  `ALTER TABLE posting DISABLE TRIGGER posting_append_only` and an `UPDATE` in one
  transaction, and a superuser's `session_replication_role = replica` skips every trigger
  enabled the default way, while `ENABLE ALWAYS` keeps one firing. So the application
  never connects as the owner. Row triggers do not fire on `TRUNCATE`, which passed until
  a statement trigger of its own was added:

  ```sql
  CREATE FUNCTION posting_is_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
  BEGIN
    RAISE EXCEPTION 'postings are append-only; book a reversal instead';
  END $$;

  CREATE TRIGGER posting_append_only BEFORE UPDATE OR DELETE ON posting
    FOR EACH ROW EXECUTE FUNCTION posting_is_append_only();
  CREATE TRIGGER posting_no_truncate BEFORE TRUNCATE ON posting
    FOR EACH STATEMENT EXECUTE FUNCTION posting_is_append_only();
  ```

## Double entry

- The postings of every journal entry sum to zero in each currency. An FX conversion is
  balanced in each currency on its own, through a conversion account per currency.
- The domain type that builds an entry refuses an unbalanced one. Where more than one
  writer reaches the table, the database checks it again at commit:

  ```sql
  CREATE FUNCTION journal_entry_balances() RETURNS trigger LANGUAGE plpgsql AS $$
  BEGIN
    IF EXISTS (SELECT 1 FROM posting WHERE journal_entry_id = NEW.journal_entry_id
               GROUP BY currency HAVING sum(amount) <> 0) THEN
      RAISE EXCEPTION 'journal entry % does not balance', NEW.journal_entry_id;
    END IF;
    RETURN NULL;
  END $$;

  CREATE CONSTRAINT TRIGGER posting_balances AFTER INSERT ON posting
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION journal_entry_balances();
  ```

  An entry is written in one transaction. The check runs at `COMMIT`, so the entry's
  postings may be inserted one at a time. A commit of an unbalanced entry failed, and so
  did a commit of an entry that set +10.00 CHF against -10.00 EUR.
- Sums and comparisons use `compareTo` or `signum()`, never `equals` (`money.md` explains
  why).

## Balances and positions are derived

- A balance or a position is computed from postings. A stored balance is a cache, and a
  rebuild from the postings reproduces it.
- A checkpoint records a balance as of a point in the postings, is written once and is
  never edited. A rebuild takes the checkpoint and adds the postings after its point. A
  scheduled full rebuild from the first posting compares itself with the checkpoints, and a
  difference raises an alert.
- The point must be one that no later commit can fall behind. An identity column is
  assigned at insert, not at commit: a slow transaction took ids 8 and 9, a faster one took
  10 and 11 and committed first, and a checkpoint at id 11 would have missed 8 and 9 for
  good. A checkpoint therefore covers a business day that is closed to new postings, and
  the rebuild adds the postings booked after that day.
- Closing a day must wait for every transaction still booking into it, or a slow one lands
  behind the checkpoint the same way. A plain read of the day's `closed` flag does not
  wait, and neither does a foreign key to the day: a posting inserted before the close and
  committed after it was missing from the checkpoint. Each posting reads its day's row
  `FOR SHARE`. The close's update of that row waits for those transactions. The close then
  commits, and the checkpoint sums in a later transaction. A close that summed in its own
  transaction got every posting under `READ COMMITTED` and missed the slow one under
  `REPEATABLE READ`.

## Reconciliation

- Reconciliation compares the ledger with an outside record for one account and one
  period: a bank statement, a custodian's position report, a counterparty's confirmation.
  Each line ends either matched or as a break.
- A break is a record of its own: both sides, the difference, a reason (missing on our
  side, missing on theirs, amount, date, currency), the date it was found and an owner. It
  ages until it is resolved, and the count and age of open breaks are metrics.
- Matching uses references first: the outside record's own reference for the entry, and
  our reference where the counterparty echoes it. Amount, currency and date come next,
  within a tolerance the business states. A fuzzy match is a proposal that a person
  confirms, never an automatic close.
- A break is never closed by editing either side. It closes with a posting on our side,
  with a reversal if our posting was wrong, or with the counterparty's correction, and the
  resolution references the break. An unexplained difference goes to a suspense or rounding
  account only under a threshold the business wrote down.

## Idempotent statement import

- A statement file is imported once. Its identity is recorded (the source, the account,
  and the statement's own number or period) with a hash of its content. A file sent again
  with the same hash imports nothing new. A file with the same identity and another hash
  is a new version: its lines go through the comparison that follows, and it is never
  skipped.
- Each line has a natural key from its source: the bank's own reference for the entry,
  within the account. A unique constraint on that key with
  `INSERT … ON CONFLICT DO NOTHING` turns a repeated line into `INSERT 0 0`.
- `DO NOTHING` also drops a changed line in silence. A line sent again with 152.00 instead
  of 125.00 kept 125.00 and raised nothing. The import therefore compares each line that
  conflicted with the stored one, field by field (`IS DISTINCT FROM`), and records a
  difference as a break.
- A correction from the source arrives as a new line or a new version of the statement. An
  imported line is never updated.
- Idempotency keys and inbox tables in general: `java-reliability-messaging`, in its
  reference on transactions and idempotency.
