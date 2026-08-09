# Async boundaries, virtual threads and pools

Reference for the `java-performance-patterns` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

## Async boundaries and threading

Choose the concurrency model based on the workload shape, not on fashion.

### I/O-bound work — use virtual threads (Project Loom)

For workloads dominated by blocking I/O (DB calls, HTTP calls, broker publishes), virtual threads are now **the default on a current LTS (JDK 25)**. They let you write straightforward synchronous code (`var result = client.call(...)`) without paying the platform-thread cost, and they scale to hundreds of thousands of concurrent blocked operations.

**What changed with JDK 24 / JDK 25 LTS**: pre-JDK 24, JDBC drivers' `synchronized` internals meant virtual threads pinned on nearly every DB call — so "use virtual threads for I/O" had a hidden asterisk big enough to disqualify it for transactional request paths. JEP 491 (shipped in JDK 24, included in JDK 25 LTS) eliminates that pinning for nearly all `synchronized` usage. On the declared baseline, **virtual threads + blocking JDBC is genuinely the default**, not the aspirational answer.

**When they shine**: request handlers, Kafka listeners, HTTP clients, JDBC calls — anywhere a thread spends most of its time waiting on something external.

**Gotchas**:

- **Synchronized used to pin the carrier thread; on JDK 25 it does not.** JEP 491 covers nearly all `synchronized` usage. Residual pinning to watch for: native frames, `Object.wait` inside `synchronized`, and a handful of JDK internals not yet migrated. If the deployment target is still JDK 21 LTS, prefer `java.util.concurrent.locks.ReentrantLock` across I/O and audit `synchronized` hot paths — that caveat is obsolete on JDK 25+.
- **ThreadLocals do not scale the same way.** With millions of virtual threads, a per-thread-local allocation becomes per-virtual-thread. Use **`ScopedValue`** (finalized in JDK 25 via JEP 506) for per-request/per-task context — it inherits into forked subtasks without per-virtual-thread allocation overhead. On JDK 21 targets, fall back to lazily-allocated `ThreadLocal`s.
- **`StructuredTaskScope` is still preview.** Despite being Loom-adjacent and tempting to reach for alongside virtual threads, Structured Concurrency is still a preview API as of JDK 25 (JEP 505/525, re-preview in JDK 26). Do not use it on production paths yet — the shape will still shift. Stick with `ExecutorService` + `Future`/`CompletableFuture` for now.
- **Not a throughput multiplier on CPU-bound code.** Virtual threads do not speed up computation — they only remove the cost of blocking. A CPU-bound task on a virtual thread is the same work on a different thread abstraction.

Spring Boot enables virtual threads with `spring.threads.virtual.enabled=true` on a supporting version. Verify and profile — on older JDKs, confirm carrier threads are not pinned under load; on JDK 25+, confirm observed concurrency matches the virtual-thread model.

### CPU-bound work — dedicated bounded pool

A bounded `ExecutorService` sized to the number of cores (plus or minus) is the right shape for CPU-bound tasks: data transformation, hashing, compression, serialization at scale.

```java
int cores = Runtime.getRuntime().availableProcessors();
ExecutorService pool = Executors.newFixedThreadPool(cores);
```

Do not use virtual threads for CPU-bound work — they will happily schedule more work than you have cores to run, and the only result is scheduling overhead plus OS contention.

### Reactive (Project Reactor, WebFlux, Mutiny) — the shrinking niche

Reactive is still the right tool for specific shapes: streaming a million-row response, backpressure-sensitive pipelines, websocket fan-outs. It is **no longer the default for HTTP request handlers** — virtual threads provide the same concurrency with straightforward code. If you are not in a reactive codebase already, the burden of proof for adopting reactive style is on the proposer: show the workload that needs it.

### Never block an event loop

If the codebase uses Netty, Reactor, or any event-loop-based runtime, a synchronous blocking call on an event-loop thread freezes the whole server under load. Use `subscribeOn(Schedulers.boundedElastic())` or the equivalent, or — better — migrate to virtual threads where the answer is "just let it block."
