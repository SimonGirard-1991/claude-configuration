# Repository and messaging tests

Reference for the `java-testing-strategy` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

## Repository / database tests — Testcontainers exclusively

> **Templates:** `hexagonal-module-bootstrap/references/tests-db.md`. This section owns the *strategy* (Testcontainers vs. H2, what to assert, container lifecycle trade-offs). The reference owns the *code* (Postgres container wiring, jOOQ DSL setup, per-test cleanup).

**What lives here:** repository implementations (jOOQ, JPA, JDBC), Flyway/Liquibase migrations, schema constraints, DB-level concurrency behavior, optimistic-lock conflicts, save+outbox atomicity.

**Tools:** Testcontainers (PostgreSQL, MySQL, whatever you run in prod), JUnit 5, AssertJ. Minimal Spring context (`@DataJpaTest`, `@JooqTest`, or hand-wired `DSLContext`).

**Rules:**
- **Testcontainers, not H2.** Non-negotiable. H2 has different SQL dialect, different constraint behavior, different transaction semantics, different JSON support, different `INSERT ... ON CONFLICT` behavior. Tests that pass on H2 and fail on Postgres are a known team-killing pattern.
- **No in-memory substitutes either** (no `hsqldb`, no `derby`, no Spring Boot test slices that swap to H2 by default — disable that explicitly).
- **One container per test class is fine; one container reused across the test suite is faster.** Use Testcontainers' singleton pattern for shared containers, with proper schema cleanup between tests. Trade-off: parallelism is harder with shared containers — choose based on suite size.
- **Test the actual SQL.** For jOOQ: assert the records persist and re-load correctly, and that constraints fire. For JPA: also test that `@Version`-based optimistic locking actually throws on conflict.
- **Test migrations forward AND backward (where applicable).** If a migration adds a NOT NULL column with a backfill, run the migration against a test DB seeded with the *previous* schema's data and verify the backfill works.
- **Save + outbox atomicity is tested here, not in application tests.** This is the only place rollback semantics are real.
- **Optimistic-lock and concurrency tests live here.** For any aggregate with a `@Version` column or equivalent, write a test that loads the same aggregate from two threads/transactions, mutates both, commits both, and asserts the second commit throws `OptimisticLockingFailureException` (or jOOQ equivalent). Then assert the application-level retry path actually succeeds on retry. This is the only place the conflict path is real — unit tests can't reproduce it.
- **Idempotency-key replay tests live here too.** Insert a row with a given idempotency key, attempt to insert again, assert the second attempt is rejected by the unique constraint (not silently swallowed). Then assert the application-level handler maps the violation to a no-op result, not an error.
- **Minimal Spring context.** `@DataJpaTest`, `@JooqTest`, or `@SpringBootTest(classes = {DslConfig.class, OrderRepositoryImpl.class})`. Never `@SpringBootTest` with no `classes` argument for a repository test — it loads the world.

## Messaging / Kafka tests — Testcontainers Kafka, minimal context

> **Templates:** `hexagonal-module-bootstrap/references/kafka-adapter.md` (production code + test patterns alongside). This section owns the *strategy* (Testcontainers vs. EmbeddedKafka, what scenarios to cover). The reference owns the *code* (consumer wiring, Awaitility patterns).

**What lives here:** consumer logic, idempotency handling, DLQ routing, serialization/deserialization, integration-event publication, retry behavior.

**Tools:** Testcontainers Kafka (preferred) or `EmbeddedKafkaBroker` for very fast feedback. JUnit 5, AssertJ, Awaitility for async assertions.

**Rules:**
- **Testcontainers Kafka for trustworthy tests; `EmbeddedKafkaBroker` for fast inner-loop feedback.** Embedded Kafka is in-process and fast, but diverges from real Kafka in subtle ways (rebalance behavior, transaction semantics). At least one CI test per consumer should use Testcontainers.
- **Test the consumer end-to-end:** publish a real message → wait for the consumer's side effect → assert. Use Awaitility, not `Thread.sleep`.
- **Test idempotency explicitly.** Replay the same message twice; assert the side effect happens once. This is the most commonly missed test in messaging code.
- **Test DLQ routing.** Publish a poison message; assert it lands in the DLQ with full context (original payload, error, headers).
- **Test serialization both directions.** Producer-side: confirm the published bytes deserialize against the schema. Consumer-side: confirm the consumed bytes deserialize correctly with both forward- and backward-compatible schema changes.
- **Minimal Spring context.** `@SpringBootTest(classes = {KafkaConfig.class, OrderConsumer.class, ...})`, never load the full app.
- **Awaitility timeouts must be generous but bounded.** 5–10 seconds for local; never `Awaitility.await().forever()`.
