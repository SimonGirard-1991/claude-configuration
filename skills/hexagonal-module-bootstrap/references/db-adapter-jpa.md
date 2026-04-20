# JPA Repository Adapter

## Read this first

**Default persistence in this skill is jOOQ.** See `db-adapter-jooq.md`. This file exists because JPA is a legitimate choice for some projects, not because it's forbidden.

The real rule isn't "JPA bad, jOOQ good" — it's:

> **Never confuse a JPA entity with a domain aggregate. Use JPA only when its trade-offs are understood and assumed.**

JPA is a reasonable choice when:
- Aggregates are small and transactional.
- Write QPS is moderate.
- The team is experienced with Hibernate semantics (`flush` timing, lazy loading, dirty checking, cache tiers).
- Read-heavy queries are handled via explicit projections (`@Query`, entity graphs, or read-side views).
- Productivity gains from Spring Data outweigh the loss of SQL control.

Consider jOOQ (or migrating hot paths to jOOQ) when:
- You find yourself writing `@Query(nativeQuery = true)` in many places.
- You regularly fight `LazyInitializationException` or N+1 issues.
- You need precise execution plans for specific queries.
- Schema / query shape matters more than object-relational mapping convenience.

Both can coexist in the same codebase — JPA for simple transactional writes, jOOQ for read models and complex queries.

---

## Hexagonal rule that still applies

**Your JPA entity is NOT your aggregate.** Keep them separate:

- `domain/model/Order.java` → pure aggregate, no JPA annotations.
- `infrastructure/db/jpa/OrderEntity.java` → JPA-annotated persistence class.
- `infrastructure/db/mapper/OrderEntityMapper.java` → converts both directions.

Skipping the mapper and annotating the aggregate with `@Entity` is the most common mistake — it pins your domain to JPA forever. Don't.

---

## Package layout

```
order/infrastructure/db/
├── jpa/
│   ├── OrderEntity.java
│   ├── OrderLineEntity.java
│   └── OrderJpaRepository.java          (Spring Data interface)
├── repository/
│   └── OrderRepositoryJpa.java          (implements application port)
└── mapper/
    └── OrderEntityMapper.java
```

## Entities

```java
// order/infrastructure/db/jpa/OrderEntity.java
package com.company.ecom.order.infrastructure.db.jpa;

import jakarta.persistence.*;
import java.math.BigDecimal;
import java.util.*;

@Entity
@Table(name = "orders")
public class OrderEntity {

  @Id
  private UUID id;

  @Column(name = "customer_id", nullable = false)
  private UUID customerId;

  @Column(nullable = false)
  private String status;

  // Rule: total is NOT stored — recomputed from lines. Same decision as the jOOQ schema
  // in db-adapter-jooq.md. Keep the two adapter templates structurally aligned.

  // Rule: JPA provides optimistic locking out of the box via @Version.
  // Hibernate bumps this column automatically on every successful update and throws
  // jakarta.persistence.OptimisticLockException when the WHERE clause finds no row
  // at the expected version. The domain aggregate carries its own `version` — map them
  // 1:1 in the mapper. After flush, Hibernate's version is authoritative; sync the
  // aggregate back with order.markPersistedAtVersion(entity.getVersion()).
  @Version
  @Column(nullable = false)
  private long version;

  @OneToMany(mappedBy = "order", cascade = CascadeType.ALL, orphanRemoval = true, fetch = FetchType.EAGER)
  private List<OrderLineEntity> lines = new ArrayList<>();

  protected OrderEntity() {}

  // getters/setters omitted for brevity
}
```

```java
// order/infrastructure/db/jpa/OrderLineEntity.java
@Entity
@Table(name = "order_lines")
public class OrderLineEntity {
  @Id private UUID id;
  @ManyToOne(fetch = FetchType.LAZY) @JoinColumn(name = "order_id") private OrderEntity order;
  @Column(nullable = false) private String sku;
  @Column(nullable = false) private int quantity;
  @Column(name = "unit_price", nullable = false) private BigDecimal unitPrice;
  @Column(nullable = false, length = 3) private String currency;
  protected OrderLineEntity() {}
}
```

## Spring Data interface

```java
// order/infrastructure/db/jpa/OrderJpaRepository.java
public interface OrderJpaRepository extends JpaRepository<OrderEntity, UUID> {}
```

## Port implementation

```java
// order/infrastructure/db/repository/OrderRepositoryJpa.java
import com.company.ecom.order.application.exception.ConcurrentAggregateModificationException;

@Repository
public class OrderRepositoryJpa implements OrderRepository {

  private final OrderJpaRepository jpa;
  private final OrderEntityMapper mapper;

  public OrderRepositoryJpa(OrderJpaRepository jpa, OrderEntityMapper mapper) {
    this.jpa = jpa;
    this.mapper = mapper;
  }

  @Override
  public void save(Order order) {
    try {
      var existing = jpa.findById(order.id().value());

      // Critical: without this pre-merge check, the load-then-merge pattern bypasses
      // optimistic locking. findById returns the *current* DB version, which we'd then
      // silently overwrite. The aggregate's own version is the concurrency token the
      // caller holds; compare it against what the DB actually has right now.
      if (existing.isPresent() && existing.get().getVersion() != order.version()) {
        throw new ConcurrentAggregateModificationException(order.id(), order.version());
      }

      var entity = existing.orElseGet(OrderEntity::new);
      mapper.mergeInto(entity, order);
      var saved = jpa.saveAndFlush(entity);                    // flush now so @Version bumps
      order.markPersistedAtVersion(saved.getVersion());        // sync the aggregate token
    } catch (jakarta.persistence.OptimisticLockException e) {
      // Hibernate throws this at flush if a concurrent transaction slipped in between
      // findById and saveAndFlush (tight race that the pre-merge check cannot see).
      // Translate at the port boundary so application/domain code never sees a
      // jakarta.persistence.* exception.
      throw new ConcurrentAggregateModificationException(order.id(), order.version());
    }
  }

  @Override
  public Optional<Order> findById(OrderId id) {
    return jpa.findById(id.value()).map(mapper::toDomain);
  }
}
```

## Mapper

```java
// order/infrastructure/db/mapper/OrderEntityMapper.java
@Component
public class OrderEntityMapper {

  public Order toDomain(OrderEntity e) {
    var lines = e.getLines().stream()
        .map(l -> new OrderLine(
            l.getId(), l.getSku(), l.getQuantity(),
            new Money(l.getUnitPrice(), Currency.getInstance(l.getCurrency()))))
        .toList();
    return Order.rehydrate(
        new OrderId(e.getId()), e.getCustomerId(), lines,
        OrderStatus.valueOf(e.getStatus()), e.getVersion());
  }

  public void mergeInto(OrderEntity target, Order source) {
    target.setId(source.id().value());
    target.setCustomerId(source.customerId());
    target.setStatus(source.status().name());
    // Do NOT copy `version` from source onto target — Hibernate owns this column via @Version.
    // If target is detached (found by id), its existing version is the lock cursor.
    // Rebuild lines — simplest correct approach; optimize with a diff if needed.
    target.getLines().clear();
    source.lines().forEach(l -> {
      var le = new OrderLineEntity();
      // set fields, attach to parent
      target.getLines().add(le);
    });
  }
}
```

## Notes

- **Keep entities dumb**. No business methods on `OrderEntity` — all behavior lives on `Order`.
- **Be explicit about fetch strategies**. Default JPA laziness leaks transaction scope.
- **Watch for N+1 queries**. If you see them, you've already grown past JPA's comfort zone — migrate to jOOQ.
- **Never return `OrderEntity` from a port**. The port deals in `Order`, always.
