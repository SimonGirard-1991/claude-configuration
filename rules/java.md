---
paths:
  - "**/*.java"
  - "**/pom.xml"
  - "**/build.gradle"
  - "**/build.gradle.kts"
  - "**/*.avsc"
  - "**/*.avdl"
  - "**/*.proto"
  - "**/openapi/**"
  - "**/openapi*.yaml"
  - "**/openapi*.yml"
  - "**/*-api.yaml"
  - "**/*-api.yml"
---
# Java conventions

The contract globs above are deliberate: the rule that a schema change *is* a code change
cannot fire from a `**/*.java` scope, because the file being edited is the `.avsc`.

## Stack
- Records for value objects and DTOs; static factory methods for mapping between layers.
- No Lombok and no MapStruct on new code. MapStruct only for genuinely many DTO
  representations, justified. On a legacy module already using them, do not remove them
  and do not extend them to new modules.
- jOOQ over Hibernate/JPA; JPA only for simple CRUD with no complex queries, justified.
- Current LTS features only; verify availability rather than assume.
- Sonar main-code idioms that recur: unused catch parameter takes `_` (java:S7467);
  identical catch bodies collapse to multi-catch (java:S2147).

## Architecture defaults

- **A modular monolith is the default; microservices are an escalation.** Never answer
  "should we extract X?" from here — the drivers that justify an actual extraction are in
  `hexagonal-ddd-java`. What is settled here is the burden of proof: extraction needs a
  concrete driver, not a preference.
- **Contract-first at every boundary crossing a service or team**, plain CRUD services
  included:
  - **REST** — the OpenAPI spec is the source of truth and code is generated from it.
    Commit the spec, not the generated code.
  - **Async events** — Avro/Protobuf with Schema Registry and an explicit compatibility
    rule: BACKWARD by default, FULL for critical contracts.
  - **Consumer-driven contract tests** (Pact, Spring Cloud Contract) whenever consumer and
    producer sit in different teams or release cycles.
  - Exceptions: purely internal endpoints, in-process domain events between modules of a
    monolith (a record suffices), and throwaway spikes — retrofitted before prod.
  - Generator settings and the `openapi-diff` CI gate live in
    `hexagonal-module-bootstrap` → `references/rest-adapter.md`. Load it before setting up
    or reviewing an actual pipeline.
- **SOLID is non-negotiable**, DIP at layer boundaries above all — it is what makes the
  hexagon work.

## Non-functional priorities

Ordered by priority, not by effort. 2–5 state the priority only; their rules are in the
skills named.

1. **Maintainability** — readable in two years by someone who did not write it. Clarity
   over cleverness. *(Owned here.)*
2. **Observability** — if you cannot see it, you cannot operate it. → `java-observability`
3. **Security** — never an afterthought. → `java-security-baseline`
4. **Reliability** — correct under partial failure. → `java-reliability-messaging`
5. **Performance** — p99, not averages; profile before optimizing.
   → `java-performance-patterns`
6. **Throughput** — stateless services, partitioned consumers, pooled connections.
   *(Owned here.)*

## Delegated expertise
Before designing, implementing, advising or reviewing in hexagonal/DDD, observability,
security, reliability/messaging, performance or testing, load the matching `java-*` or
`hexagonal-*` skill and read the reference file its map points to. Thresholds and
checklists live there, not in memory.

## Review scope

**Judge a diff by what it does, not by its file extension.** A changed `.avsc`, `.proto`
or `openapi.yaml` is a contract change carrying compatibility and validation consequences,
and it gets a real review — it is not documentation. Only prose (README, comments, ADRs)
is genuinely out of scope. And when a dimension is arguable, run it: the cost of loading a
skill you did not strictly need is tokens, the cost of skipping one you did is a defect
shipped by a review that reported clean.

## Verification after non-trivial changes
1. Compile and run the targeted tests.
2. If the repo has a `.sonar-gate` file, run `~/.claude/scripts/sonar-gate.sh`
   (`--project-dir` for the repo); fix or justify every finding on the same line,
   and list every suppression in the hand-back.
3. Spawn `code-reviewer` with: what changed and why, the calibration tier
   (throwaway / internal tool / production service / critical financial system), the
   scope (paths or git range), and the line
   `Invocation: self-review loop, iteration N of 3`. Address 🔴 and 🟡; judge 🔵 on
   merit; cap at 3 iterations, then escalate to the user with what is outstanding.
Relay any **Proposed memory** note verbatim; record it only on user approval.
