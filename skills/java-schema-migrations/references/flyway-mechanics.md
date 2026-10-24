# Flyway mechanics

How Flyway runs PostgreSQL migrations, and the settings the online changes need. The facts
were checked on 2026-10-23 with Flyway 13.11.1 (CLI, Maven plugin and Java API), Spring
Boot 4.1.2 with the Flyway 12.4.0 it manages, PostgreSQL 18.6, jOOQ 3.21.9 and
Testcontainers 2.0.5, and on 2026-10-24 for the failure path. Redgate's pages on
[transactions](https://documentation.red-gate.com/fd/migration-transaction-handling-273973399.html),
[script configuration](https://documentation.red-gate.com/fd/reference/script-configuration),
[the transactional lock](https://documentation.red-gate.com/fd/reference/configuration/flyway-namespace/flyway-postgresql-namespace/flyway-postgresql-transactional-lock-setting),
[callback events](https://documentation.red-gate.com/fd/reference/callback-events) and
[repair](https://documentation.red-gate.com/fd/repair-277578892.html) are the sources, with
jOOQ's [DDLDatabase](https://www.jooq.org/doc/latest/manual/code-generation/codegen-ddl/)
and [version control](https://www.jooq.org/doc/latest/manual/code-generation/codegen-version-control/)
pages.

## Contents

- Transactions
- Concurrent index builds and Flyway's lock
- Session settings
- A failed migration and repair
- Locations and one version sequence
- jOOQ code generation from the migrations
- Testing a migration against the previous schema's data

## Transactions

- Each migration runs in its own transaction. On PostgreSQL a failed one rolls back and
  leaves no row in `flyway_schema_history`.
- Flyway detects a statement that cannot run in a transaction, such as
  `CREATE INDEX CONCURRENTLY`, and runs that migration outside one. The log marks it
  `[non-transactional]`.
- A migration that mixes such a statement with transactional ones fails: "Detected both
  transactional and non-transactional statements within the same migration (even though
  mixed is false)". `mixed=true` runs the whole migration outside a transaction, so a
  failure halfway leaves its first statements applied. A non-transactional statement gets
  a migration of its own instead.
- A `SET` counts as transactional, so a `SET lock_timeout` beside a concurrent build made
  the migration a mix too. That migration turns the transaction off itself, as below.
- Flyway does not detect a `DO` block that commits, which then fails inside the
  transaction. A script configuration file beside the migration turns the transaction off:
  `V12__shipments_service_level_backfill.sql.conf` holding `executeInTransaction=false`.
  With it, a `DO` block that committed after each batch ran three batches in three
  transactions.

## Concurrent index builds and Flyway's lock

- By default Flyway holds a transactional advisory lock for the whole run, on a connection
  of its own. A concurrent build waited for that open transaction of Flyway's own, so it
  never finished. Startup hung with the build waiting on `virtualxid` and Flyway's
  connection idle in transaction, on Flyway 13.11.1 and on Spring Boot 4.1.2's 12.4.0.
  Under a `lock_timeout` it failed with "canceling statement due to lock timeout" instead.
- A session-level lock fixes it. Each runner below set it and then completed a concurrent
  build:

  | Runner | Setting |
  |---|---|
  | Spring Boot | `spring.flyway.postgresql.transactional-lock=false` |
  | Maven plugin | `<pluginConfiguration><postgresql.transactional.lock>false</postgresql.transactional.lock></pluginConfiguration>`. The documented `<postgresqlTransactionalLock>` element failed with "Unknown configuration property: flyway.postgresqlTransactionalLock" |
  | Maven plugin, from the environment | `FLYWAY_POSTGRESQL_TRANSACTIONAL_LOCK=false` |
  | CLI | `-postgresql.transactional.lock=false` |
  | Java API | `configuration.getConfigurationExtension(PostgreSQLConfigurationExtension.class).setTransactionalLock(false)`. The same key passed through `configuration(Map)` asked for jackson-databind on the classpath |

- The build's own migration, its invalid leftovers and its `lock_timeout` are in
  `online-changes.md` § Indexes.

## Session settings

- A `SET` in one migration was still in force in the next migration of the same run, both
  inside and outside a transaction.
- `beforeEachMigrate.sql` in the migrations location runs before every migration, so it
  sets the run's values for each one:

  ```sql
  SET lock_timeout = '5s';
  SET client_connection_check_interval = '1s';
  ```

  - Every migration ran under it, on Flyway 13.11.1 from the CLI and on Spring Boot
    4.1.2's Flyway 12.4.0, with the transactional lock on or off. A migration that set a
    longer `lock_timeout` for itself did not pass it on: the next one ran under the
    callback's again.
  - `afterConnect.sql` reached the migrations on 13.11.1, but on 12.4.0 only with the
    transactional lock off. With the lock on, it ran on a connection the migrations did not
    use, and they ran with `lock_timeout = 0`. `initSql` warned on 13.11.1 that it is
    deprecated in favour of `afterConnect`.
  - `SELECT current_setting('lock_timeout')` inside a migration shows what a runner applies.
- Under Spring Boot, Flyway borrows a connection from the application's pool unless
  `spring.flyway.user` or `spring.flyway.url` is set. With the transactional lock off, the
  migrations ran on one pooled connection, which went back to the pool holding the
  callback's `lock_timeout` and `client_connection_check_interval`. The application's
  queries on it then ran under them, until HikariCP retires the connection (`maxLifetime`,
  30 minutes by default in 7.0.2).
  - The repo's policy gives migrations a role of their own (`types-and-naming.md`
    § Privileges for the application role), which also avoids this. With
    `spring.flyway.user` set, the migrations ran on a connection outside the pool, and the
    pool stayed clean.
  - Where Flyway must share the pool, an `afterEachMigrate.sql` holding
    `RESET lock_timeout;` and `RESET client_connection_check_interval;` left every pooled
    connection at its defaults after a successful run, on 12.4.0 and 13.11.1. The next
    migration still ran under `beforeEachMigrate.sql`'s value.
  - `afterEachMigrate` runs only after a successful migration, and `afterEachMigrateError`
    after a failed one. A failed transactional migration rolled the callback's `SET`s back
    with it. A failed non-transactional one left its connection in the pool with
    `lock_timeout = 10min`, on both versions. Under Boot, a failed migration also failed
    the application's startup, and HikariCP shut the pool down.
- In a transactional migration, `SET LOCAL` changes a setting for that migration only. In a
  non-transactional one, `SET LOCAL` does nothing and warns "SET LOCAL can only be used in
  transaction blocks", and a `SET` lasts into the next migrations. So a non-transactional
  migration sets back, at its end, any setting the callback does not set.

## A failed migration and repair

- A non-transactional migration that fails is recorded with `success = false`. Every later
  `migrate` then stops with "Validate failed: Migrations have failed validation. Detected
  failed migration to version N". What its statements did stays done: a failed concurrent
  build leaves its invalid index.
- A transactional migration that fails leaves nothing to repair on PostgreSQL.
- `repair`, as the Migrations bullet of `~/.claude/conventions/java.md` § Stack says:
  - deletes the failed rows;
  - realigns the checksums, descriptions and types of applied migrations with the files: an
    edited applied migration failed `validate` with "Migration checksum mismatch for
    migration version N" until a repair;
  - marks an applied migration whose file is gone as deleted, with a `DELETE` row, so it
    needs the same `locations` as `migrate`;
  - never re-runs a migration recorded as successful: after the checksum repair, the edited
    migration's insert had still run once.
- Recovering from a failed non-transactional migration takes four steps: fix the cause,
  remove what it left or let the migration remove it, run `repair`, and deploy again. A
  rerun of `CREATE INDEX CONCURRENTLY IF NOT EXISTS` over an invalid leftover was recorded
  as a success while the index stayed invalid.
- Fixing the cause may mean editing the failed migration, which is the one edit a shared
  migration takes. Where it had already succeeded, the edit must leave its effect
  unchanged, and `repair` there realigns its checksum without re-running it.

## Locations and one version sequence

- `locations` may list one directory per module. Flyway merges them into one sequence and
  applies the versions in order across them: V1 from the first, V2 from the second, V3 from
  the first again.
- The same version in two locations fails: "Found more than one migration with version 4".
  So the modules draw their versions from one shared sequence.
- A version lower than one already applied, for instance one merged later from another
  branch, fails validation: "Detected resolved migration not applied to database: 3.1".
  `outOfOrder=true` applies it, marked `[out of order]`. A repo chooses one policy:
  renumber the migration before it is shared, or allow out-of-order versions where
  branches merge in any order.

## jOOQ code generation from the migrations

- The generated classes come from the schema the migrations build. jOOQ's manual treats two
  models as valid:
  - **Regenerated on every build**, as in the snippet below. The code and the migrations
    cannot drift, but every build needs a database.
  - **Committed**, as `hexagonal-module-bootstrap` does, so a build needs no database. The
    same executions sit in a profile run on demand, with `<target><directory>` set to the
    committed path. CI runs that profile and fails on `git diff --exit-code`: two
    regenerations from fresh databases came out byte-identical.
- **From a real PostgreSQL.** Flyway's Maven plugin migrates a database the build is given,
  and jOOQ's plugin then generates from it, both in `generate-sources`, Flyway first. The
  output had the NOT NULL columns, the identity column and the indexes the migrations
  declare. The database is a throwaway one, since Flyway migrates whatever the URL names:
  a CI service container, or a local `postgres:18.6` container.

  ```xml
  <plugin>
    <groupId>org.flywaydb</groupId>
    <artifactId>flyway-maven-plugin</artifactId>
    <version>${flyway.version}</version>
    <executions>
      <execution><phase>generate-sources</phase><goals><goal>migrate</goal></goals></execution>
    </executions>
    <dependencies>
      <dependency><groupId>org.flywaydb</groupId><artifactId>flyway-database-postgresql</artifactId><version>${flyway.version}</version></dependency>
      <dependency><groupId>org.postgresql</groupId><artifactId>postgresql</artifactId><version>${postgresql.version}</version></dependency>
    </dependencies>
    <configuration>
      <url>${codegen.db.url}</url>
      <user>${codegen.db.user}</user>
      <password>${codegen.db.password}</password>
      <locations><location>filesystem:src/main/resources/db/migration</location></locations>
      <pluginConfiguration><postgresql.transactional.lock>false</postgresql.transactional.lock></pluginConfiguration>
    </configuration>
  </plugin>
  <plugin>
    <groupId>org.jooq</groupId>
    <artifactId>jooq-codegen-maven</artifactId>
    <version>${jooq.version}</version>
    <executions>
      <execution><phase>generate-sources</phase><goals><goal>generate</goal></goals></execution>
    </executions>
    <dependencies>
      <dependency><groupId>org.postgresql</groupId><artifactId>postgresql</artifactId><version>${postgresql.version}</version></dependency>
    </dependencies>
    <configuration>
      <jdbc><url>${codegen.db.url}</url><user>${codegen.db.user}</user><password>${codegen.db.password}</password></jdbc>
      <generator>
        <database>
          <name>org.jooq.meta.postgres.PostgresDatabase</name>
          <inputSchema>public</inputSchema>
          <excludes>flyway_schema_history</excludes>
        </database>
        <target><packageName>com.example.db</packageName></target>
      </generator>
    </configuration>
  </plugin>
  ```

- **From the scripts alone.** jOOQ's `DDLDatabase`, in `jooq-meta-extensions`, needs no
  database: it parses the scripts and replays them into an in-memory H2. Its parser refused
  `CREATE INDEX CONCURRENTLY`, `DROP INDEX CONCURRENTLY`, `CHECK … NOT VALID` and
  PostgreSQL 18's `NOT NULL … NOT VALID`. `-- [jooq ignore start]` and
  `-- [jooq ignore stop]` around them let it finish, and the output then lacked the index
  and declared the column nullable. It fits only a schema built from plain DDL.
- `testcontainers-jooq-codegen-maven-plugin` 0.0.4, its latest release, bundles Flyway
  9.16.3 and jOOQ 3.18.3, so it does not run the project's Flyway.

## Testing a migration against the previous schema's data

- A test that migrates an empty schema cannot see a backfill that misses rows. Flyway's
  `target` stops at a version, so the test migrates to the version before the change,
  writes rows the way the previous release writes them, migrates to the latest, and
  asserts on the value the backfill wrote. A backfill that wrote the wrong value failed
  this assertion ("expected: <2> but was: <0>"), which a later `VALIDATE` cannot catch.
  With the backfill removed, the validating migration failed first: "column … contains
  null values".

  ```java
  @Testcontainers
  class ServiceLevelMigrationTest {

      @Container
      static final PostgreSQLContainer POSTGRES = new PostgreSQLContainer("postgres:18.6");

      @Test
      void backfillFillsRowsWrittenByThePreviousRelease() throws SQLException {
          // Arrange
          flywayTo("11").migrate();
          execute("INSERT INTO shipments (carrier_id) VALUES (1), (2)");

          // Act
          flywayTo("latest").migrate();

          // Assert
          assertEquals(2, count("SELECT count(*) FROM shipments WHERE service_level = 'standard'"));
      }

      private static Flyway flywayTo(String target) {
          FluentConfiguration configuration = Flyway.configure()
                  .dataSource(POSTGRES.getJdbcUrl(), POSTGRES.getUsername(), POSTGRES.getPassword())
                  .target(target);
          configuration.getConfigurationExtension(PostgreSQLConfigurationExtension.class).setTransactionalLock(false);
          return configuration.load();
      }
  }
  ```

  `execute` and `count` are plain JDBC helpers. `PostgreSQLContainer` is
  `org.testcontainers.postgresql.PostgreSQLContainer` in Testcontainers 2, from
  `org.testcontainers:testcontainers-postgresql`.
- The container runs production's PostgreSQL major, as `java-testing-strategy` requires.
  The test turns the transactional lock off as above, or a concurrent build in the
  migrations hangs it.
- Each such test starts from an empty database. The static container is already at the
  latest version once one test has run, so a second test method gets a database of its
  own.
- Maven keeps a deleted or renamed migration in `target/classes` until `mvn clean`, so a
  test run after such a change still applies the old file. A removed backfill passed
  without `clean` and failed with it.
