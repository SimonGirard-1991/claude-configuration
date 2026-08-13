# jOOQ Repository Adapter (default)

Driven adapter in `infrastructure/db/`. Implements the `OrderRepository` port from `application/`. Full SQL control, no ORM magic.

Package layout:
```
order/infrastructure/db/
├── repository/
│   └── OrderRepositoryJooq.java
└── mapper/
    ├── OrderRecordMapper.java       (jOOQ Record → domain Order)
    └── OrderRowWriter.java          (domain Order → jOOQ insert/update fields)
```

jOOQ-generated classes live under `src/main/generated-jooq/` and are committed to git (same as Wealthpay's convention).

---

## Migration reminder

Flyway migrations live in `src/main/resources/db/migration/`. Representative schema:

```sql
-- V1__order_schema.sql
CREATE TABLE orders (
  id          UUID PRIMARY KEY,
  customer_id UUID NOT NULL,
  status      TEXT NOT NULL,
  version     BIGINT NOT NULL DEFAULT 0,   -- optimistic lock cursor
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Rule: `total` is intentionally NOT stored here. Order.total() is recomputed from lines.
-- Storing a redundant total creates two sources of truth that can drift.
-- For query patterns like "orders > 100 EUR", build a dedicated read model rather than
-- denormalizing into the write table.
CREATE TABLE order_lines (
  id          UUID PRIMARY KEY,
  order_id    UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  sku         TEXT NOT NULL,
  quantity    INT  NOT NULL CHECK (quantity > 0),
  unit_price  NUMERIC(19, 4) NOT NULL,
  currency    CHAR(3) NOT NULL
);

CREATE INDEX idx_order_lines_order_id ON order_lines(order_id);
```

## Repository implementation

```java
// order/infrastructure/db/repository/OrderRepositoryJooq.java
package com.company.ecom.order.infrastructure.db.repository;

import com.company.ecom.order.application.exception.ConcurrentAggregateModificationException;
import com.company.ecom.order.application.port.OrderRepository;
import com.company.ecom.order.domain.model.Order;
import com.company.ecom.order.domain.model.OrderId;
import com.company.ecom.order.infrastructure.db.mapper.OrderRecordMapper;

import org.jooq.DSLContext;
import org.springframework.stereotype.Repository;

import java.util.Optional;

import static com.company.ecom.generated.jooq.Tables.ORDERS;
import static com.company.ecom.generated.jooq.Tables.ORDER_LINES;

@Repository
public class OrderRepositoryJooq implements OrderRepository {

  private final DSLContext dsl;
  private final OrderRecordMapper mapper;

  public OrderRepositoryJooq(DSLContext dsl, OrderRecordMapper mapper) {
    this.dsl = dsl;
    this.mapper = mapper;
  }

  @Override
  public void save(Order order) {
    boolean exists = dsl.fetchExists(
        dsl.selectOne().from(ORDERS).where(ORDERS.ID.eq(order.id().value())));

    if (!exists) {
      dsl.insertInto(ORDERS)
          .set(ORDERS.ID, order.id().value())
          .set(ORDERS.CUSTOMER_ID, order.customerId())
          .set(ORDERS.STATUS, order.status().name())
          .set(ORDERS.VERSION, order.version())
          .execute();
    } else {
      long newVersion = order.version() + 1;
      int updated = dsl.update(ORDERS)
          .set(ORDERS.STATUS, order.status().name())
          .set(ORDERS.VERSION, newVersion)
          .set(ORDERS.UPDATED_AT, java.time.OffsetDateTime.now())
          .where(ORDERS.ID.eq(order.id().value()))
          .and(ORDERS.VERSION.eq(order.version()))
          .execute();
      if (updated == 0) {
        throw new ConcurrentAggregateModificationException(order.id(), order.version());
      }
      order.markPersistedAtVersion(newVersion);
    }

    dsl.deleteFrom(ORDER_LINES).where(ORDER_LINES.ORDER_ID.eq(order.id().value())).execute();

    var batch = dsl.batch(
        dsl.insertInto(ORDER_LINES,
                ORDER_LINES.ID, ORDER_LINES.ORDER_ID, ORDER_LINES.SKU,
                ORDER_LINES.QUANTITY, ORDER_LINES.UNIT_PRICE, ORDER_LINES.CURRENCY)
            .values((java.util.UUID) null, null, null, null, null, null));
    for (var line : order.lines()) {
      batch.bind(
          line.id(), order.id().value(), line.sku(),
          line.quantity(), line.unitPrice().amount(), line.unitPrice().currency().getCurrencyCode());
    }
    batch.execute();
  }

  @Override
  public Optional<Order> findById(OrderId id) {
    var header = dsl.selectFrom(ORDERS).where(ORDERS.ID.eq(id.value())).fetchOne();
    if (header == null) return Optional.empty();

    var lineRecords = dsl.selectFrom(ORDER_LINES)
        .where(ORDER_LINES.ORDER_ID.eq(id.value()))
        .fetch();

    return Optional.of(mapper.toDomain(header, lineRecords));
  }
}
```

## Mapper

```java
// order/infrastructure/db/mapper/OrderRecordMapper.java
@Component
public class OrderRecordMapper {

  public Order toDomain(OrdersRecord header, Result<OrderLinesRecord> lineRecords) {
    var lines = lineRecords.stream()
        .map(l -> new OrderLine(
            l.getId(),
            l.getSku(),
            l.getQuantity(),
            new Money(l.getUnitPrice(), Currency.getInstance(l.getCurrency()))))
        .toList();
    return Order.rehydrate(
        new OrderId(header.getId()),
        header.getCustomerId(),
        lines,
        OrderStatus.valueOf(header.getStatus()),
        header.getVersion());
  }
}
```

## Transaction handling

- Transactions are declared in `application/` on the committer bean (`@Transactional` on `PlaceOrderCommitter.commit(...)`, not on the orchestrating service — see `use-case.md` for the two-bean split and why).
- The repository does not open its own transaction; it joins the ambient one.
- For cross-aggregate reads, consider a dedicated read service with jOOQ fetching projections directly — see `hexagonal-ddd-java` → Queries and read models.

## Notes

- **Commit generated jOOQ classes** to git if you use OSS jOOQ (requires a live DB for codegen). Alternative: run codegen in CI and cache.
- **Never leak jOOQ `Record` types past the repository**. Map at the boundary.
- **For aggregate updates with concurrency semantics, prefer optimistic locking** (`WHERE version = ?`) as shown in the `save` implementation above. That is why `save` branches on `fetchExists` instead of issuing an upsert: the INSERT/UPDATE split keeps the locking unambiguous, where an upsert would silently clobber a concurrent update. Use `onConflict...doUpdate` (Postgres upsert) only for simple idempotent inserts or projections where clobbering is acceptable (e.g., a read-model table keyed on a natural identifier, or an idempotent outbox dispatch record).
- **The insert branch assumes server-generated IDs.** `UUID.randomUUID()` in the application service makes a PK collision astronomically unlikely, so the template does not guard it. If IDs become client-provided — derived from an idempotency key, say — two parallel inserts can race: catch the resulting `DataIntegrityViolationException` there and map it to the application-level conflict your API already expects (409 / `ABORTED`), not a raw 500.
- **Lines are deleted and reinserted on every save**, the simplest correct strategy for a small aggregate. The optimistic-lock check above guards against concurrent writers, so replacing lines within the same transaction is safe. What it costs: per-line audit metadata (`created_at`, `updated_at`, soft-delete flags) is lost, triggers fire on every line on every save — noisy for audit tables — and the ratio of write volume to actual change is poor once aggregates grow. For large aggregates or high write volume, compute a diff instead (inserts/updates/deletes by primary key).
- **Prefer explicit columns** over `select *` in jOOQ DSL — refactoring safety.

## Variants — non-jOOQ

For non-jOOQ options, see `db-adapter-jpa.md` for the JPA trade-offs. MyBatis, JDBI, or Spring JDBC would follow the exact same shape as this file: port in `application/`, implementation in `infrastructure/db/`, explicit mapper, no persistence type leaking outward.
