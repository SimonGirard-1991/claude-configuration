---
paths:
  - "**/*.java"
  - "**/pom.xml"
  - "**/build.gradle"
  - "**/build.gradle.kts"
---
# Java conventions

## Stack
- Records for value objects and DTOs; static factory methods for mapping between layers.
- No Lombok and no MapStruct on new code. MapStruct only for genuinely many DTO
  representations, justified. On a legacy module already using them, do not remove them
  and do not extend them to new modules.
- jOOQ over Hibernate/JPA; JPA only for simple CRUD with no complex queries, justified.
- Current LTS features only; verify availability rather than assume.
- Sonar main-code idioms that recur: unused catch parameter takes `_` (java:S7467);
  identical catch bodies collapse to multi-catch (java:S2147).

## Delegated expertise
Before designing, implementing, advising or reviewing in hexagonal/DDD, observability,
security, reliability/messaging, performance or testing, load the matching `java-*` or
`hexagonal-*` skill and read the reference file its map points to. Thresholds and
checklists live there, not in memory.

## Verification after non-trivial Java changes
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
