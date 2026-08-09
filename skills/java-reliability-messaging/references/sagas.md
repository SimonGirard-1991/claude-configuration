# Sagas — choreography and orchestration

Reference for the `java-reliability-messaging` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

## Saga pattern — cross-aggregate, cross-service workflows

When a business process touches multiple aggregates or multiple services and cannot fit into a single DB transaction, use a **saga**: a sequence of local transactions, each with a **compensating action** to undo its effect.

### Choreography (preferred default)

Each service reacts to events, emits its own events, and the workflow emerges from the event graph. No central coordinator.

```
OrderPlaced → (Payment service) → PaymentAuthorized → (Inventory) → InventoryReserved → (Shipping) → Shipped
                                ↓ PaymentDeclined
                                 → (Order) → OrderCancelled
```

**When**: 2–4 steps, stable workflow, services are already event-driven.

**Pros**: no central coupling, each service owns its piece, scales naturally.

**Cons**: the workflow is implicit in the event wiring — hard to visualize and reason about as it grows. Debugging "why did this saga stop at step 3?" means tracing events across services.

### Orchestration (escalation)

A dedicated orchestrator service (or state machine) drives the workflow, calling services in sequence and issuing compensations on failure.

**When**: 5+ steps, complex conditional branching, workflow changes frequently, explicit visibility into saga state is a business requirement (audit, support, observability).

**Tools**: Camunda, Temporal, Netflix Conductor, or a hand-rolled state machine persisted in the DB. **Temporal** is a strong default once a hand-rolled state machine starts accumulating retries, timeouts, and compensations you'd otherwise have to build and test yourself — its workflow-as-code model handles all of that with deterministic replay. Not worth the operational weight for a 2-step workflow.

**Pros**: workflow is explicit and inspectable. Easier to add steps, branch, debug.

**Cons**: the orchestrator is a new deployable, a new failure domain, and a new coupling point.

### Non-negotiables for any saga

- **Every forward step has a compensating step.** Write them at the same time. A saga with no compensation for step N is a bug waiting for step N+1 to fail.
- **Compensations are idempotent.** They will be retried. `refund(paymentId)` on an already-refunded payment must be a safe no-op.
- **Compensations are not perfect rollbacks.** "Refund" is not the inverse of "charge" — the money moved, a fee was incurred, an audit trail exists. Design compensations as *business reversals*, not technical undo.
- **Saga state is persisted and observable.** For orchestration, the orchestrator persists state. For choreography, emit `SagaStepCompleted` events so the journey is reconstructable. A saga you cannot inspect is a saga you cannot operate.
- **Timeouts at every step.** A saga step that hangs forever wedges the whole workflow. Bound every wait.
