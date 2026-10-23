# Time

Which type holds which value, where the zone comes from, and how daylight saving, cutoffs,
scheduled jobs and the database treat business time. The facts were checked on 2026-10-23
on JDK 25.0.5 with tzdb 2026e, Spring Framework 7.0.10, PostgreSQL 18.6 and pgjdbc 42.7.14.

## Contents

- Which type
- The zone is always explicit
- Daylight saving
- Cutoffs
- Scheduled jobs
- Business calendars
- Postgres and JDBC

## Which type

| Value | Type |
|---|---|
| An event: booked, received, executed, sent | `Instant` |
| A civil date: value date, booking date, trade date, due date | `LocalDate` |
| A rule at a local time of day: a 16:00 cutoff, a 23:30 job | `LocalTime` with its `ZoneId` |
| A moment shown to or typed by a person, and calendar arithmetic | `ZonedDateTime`, at the edge only |
| A `timestamptz` crossing JDBC | `OffsetDateTime`, converted to `Instant` in the repository |

`LocalDateTime` never holds an event, because it names no instant. A value date and a
booking date are two `LocalDate`s, and they may differ.

## The zone is always explicit

- The `Clock` is injected, and the zone that turns its instant into a business date is
  named: `LocalDate.now(clock.withZone(BUSINESS_ZONE))`. `LocalDate.now(clock)` uses the
  clock's own zone. At 22:30Z on 2026-10-22, a UTC clock gives the 22nd, while Zurich is
  already on the 23rd.
- The JVM's default zone depends on the machine, and a developer's laptop and a server
  may differ. No business rule reads it. A test that passes only in the developer's zone
  has a hidden input, and a run with `-Duser.timezone=UTC` exposes it.
- A zone is a region ID such as `Europe/Zurich`, never a fixed offset such as `+01:00`,
  for any rule that spans the year. 14:30Z on 2026-03-30 is 16:30 in Zurich, while a fixed
  `+01:00` says 15:30.

## Daylight saving

- In 2026, Zurich's clocks jump from 02:00 to 03:00 on 29 March and fall back from 03:00 to
  02:00 on 25 October. 29 March lasts 23 hours.
- A local time in the gap moves forward: 02:30 on 29 March becomes 03:30+02:00, from
  `atZone` or `ZonedDateTime.of`, and Postgres gives the same.
- A local time in the overlap is ambiguous, and Java and Postgres resolve it differently.
  Java takes the earlier offset, 02:30+02:00 on 25 October, and `withLaterOffsetAtOverlap()`
  gives 02:30+01:00. Postgres takes the offset that holds after the transition, so in a
  Zurich session `'2026-10-25 02:30'::timestamptz` is 02:30+01. The two differ by an hour,
  so a local time never travels between them. The instant does.
- `plusDays(1)` keeps the wall-clock time, and `plusHours(24)` keeps the duration. From
  23:30 on 24 October in Zurich, they give 23:30 and 22:30 on the 25th.

## Cutoffs

A cutoff is a business date, a local time and a zone, compared as an instant:

```java
public static boolean isBefore(Instant received, LocalDate businessDate, LocalTime cutoff, ZoneId zone) {
    return received.isBefore(businessDate.atTime(cutoff).atZone(zone).toInstant());
}
```

16:00 in Zurich was 15:00Z on 27 March 2026 and 14:00Z on 30 March, so 14:30Z is before
the cutoff on the first day and after it on the second. `received` comes from the injected
`Clock`, never from `Instant.now()`, and a test fixes it with `Clock.fixed`. A cutoff
inside the hours a DST change touches needs a rule from the business, because the gap
moves it and the overlap makes it happen twice.

## Scheduled jobs

- `@Scheduled(cron = …)` without `zone` resolves in the zone of the scheduler's clock,
  which is the JVM's default unless the scheduler is given another clock.
  `0 30 23 * * *` fired at 23:30Z on a UTC JVM and at 21:30Z on a Zurich one. A business
  job names its zone: `@Scheduled(cron = "0 30 23 * * *", zone = "Europe/Zurich")`. A
  misspelt zone fails at startup with `Invalid time zone specification`.
- A cron follows the wall clock through DST. A daily job at 02:30 in Zurich did not run on
  29 March, and ran twice on 25 October, at 02:30+02:00 and at 02:30+01:00. A daily
  business job is scheduled outside the hours a DST change touches, or each run is keyed
  on its business date, so a second run finds the work already done.
- On several instances, each instance runs the job, at the same second. The key on the
  business date makes the extra runs harmless only if it is claimed atomically: a unique
  constraint on what the run books, such as each interest entry's account and business
  date, so a second insert conflicts instead of booking twice. Two concurrent runs that
  checked first and wrote after booked twice, and the same runs against a unique key
  booked once.

## Business calendars

- Weekends and holidays are data per market or currency, loaded from a maintained source.
  Code never decides a business day from `DayOfWeek` alone.
- The roll rule for a date that falls on a holiday (following, modified following,
  preceding) comes from the contract or the product's terms.
- A calendar is versioned like any reference data, and a past date is computed against
  the calendar that was valid at the time.

## Postgres and JDBC

- `timestamptz` stores an instant as UTC and shows it in the session's `TimeZone`. The
  offset it was given is not kept. `timestamp` ignores a zone in its input:
  `TIMESTAMP '2026-10-19 10:23:54+02'` stores 10:23:54. An event goes in `timestamptz`,
  and a civil date in `date`.
- `::date` on a `timestamptz` uses the session's `TimeZone`. 2026-10-22 22:30Z is the 23rd
  in a Zurich session and the 22nd in a UTC one. SQL that derives a business date names
  the zone: `(booked_at AT TIME ZONE 'Europe/Zurich')::date`.
- pgjdbc maps `timestamptz` to `OffsetDateTime` and returns it in UTC. Both
  `getObject(…, Instant.class)` and `setObject` with an `Instant` failed. The repository
  converts with `toInstant()` when it reads and with `instant.atOffset(ZoneOffset.UTC)`
  when it writes. `date` maps to `LocalDate`.
