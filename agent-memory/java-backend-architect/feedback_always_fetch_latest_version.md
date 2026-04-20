---
name: Version selection discipline — latest, compatibility, migration
description: For any dependency version decision (new pin OR bump), run the three-step discipline: fetch latest, verify compatibility, review breaking changes. Never pick a version from training data — it is effectively random.
type: feedback
---

Any time a version decision is on the table — a brand-new dependency, a bump
of an existing one, or picking a tag for a Docker image — follow a three-step
discipline. Do not short-cut any of the steps.

## Step 1 — Fetch the actual latest stable version

Use a retrieval tool. Do not recite from training data.

**Tool preference order** (use the first one actually present in the current
function list — do not assume tools exist based on the system prompt alone):

1. **Context7 MCP** (`mcp__context7__*`) — first choice for library/framework
   docs and current version. Only usable when it appears in the function list.
2. **Brave Search MCP** (`mcp__brave-search__*`) — for CVE cross-check, recent
   release notes, multi-source comparison.
3. **WebFetch** on the upstream `/releases/latest` page — always available as
   fallback.
4. **WebSearch** — last resort.

If step 1's preferred tool isn't in my function list, do NOT silently pretend
to use it. Either note the degraded tool path in the response, or ask the user
to confirm whether the MCP server should be wired up.

**By dependency type:**

- Docker images → upstream project's `/releases/latest` on GitHub, then confirm
  the tag is published on the registry path you reference (Docker Hub vs quay.io
  vs ghcr.io can diverge by days).
- Maven/Gradle artifacts → Context7 first if available, Maven Central / Gradle
  Plugin Portal otherwise.
- CLI tools → project homepage or GitHub releases.
- Spring Boot / framework stacks → the framework's release-train BOM, not the
  individual artifact, so transitive versions stay coherent.

## Step 2 — Verify compatibility with the existing stack

The latest version is not always the right version. Check:

- **Runtime compatibility** — does it need a JDK version newer than the project
  uses? A newer Postgres / Kafka / Redis? A newer OS base image?
- **Transitive compatibility** — does it force an incompatible version of a
  shared dependency (Jackson, Netty, Guava, Protobuf, gRPC)? Spring Boot
  release trains pin these for a reason; breaking the pin causes classpath
  conflicts that don't surface until runtime.
- **API / schema compatibility** — for exporters, observability agents, and
  schema-registry clients, verify the version speaks the protocol your stack
  already uses.
- **Platform compatibility** — arm64 vs amd64 for Docker images; native-image
  support for Quarkus/GraalVM if relevant.

If the latest is NOT compatible, pick the highest version that IS, and state
in the PR why you went one release short.

## Step 3 — Review breaking changes and migration cost

Before committing a bump, read:

- The **CHANGELOG** / release notes for every version between the current pin
  and the target, not just the target's notes.
- The **UPGRADING.md** / migration guide if the project publishes one.
- Any deprecation warnings introduced along the way that will turn into
  hard errors later.

Then decide:

- Is the migration in scope for THIS PR, or does it deserve its own PR?
- Are there config keys or API calls that need updating in the same diff?
- Does the bump require a data migration (e.g., Flyway, Kafka topic schema)?

For a NEW dependency, step 3 collapses to "are there known integration
gotchas?" — still worth a 30-second search.

## Why this matters

Picking a version from training data is not "a reasonable default" — it is
effectively **a random choice weighted by what was popular when the model was
trained**. Training cutoffs drift out of date fast. In the wealthpay project I
pinned `postgres_exporter:v0.15.0` in 2026-04 when `v0.19.1` was current; the
gap was four minor versions and included fixes for `pg_stat_io` collectors
that were directly on the path of the work we were about to do. That wasn't a
conservative choice. It was a non-choice dressed up as one.

## How to apply

- Before writing ANY version string, run step 1.
- Before recommending an upgrade, run all three steps.
- In the PR description / commit body, cite the source of the chosen version
  (release page + date) when the pin is non-obvious or very recent (< 30 days).
- If I find myself about to type a version number without having run step 1,
  stop and retrieve first.

## When this does NOT apply

- Existing pins already in the repo: leave alone unless the user asks to bump,
  or unless a known-exploited CVE forces the upgrade. Those are the team's
  deliberate choices and changing them is scope creep.
- Emergency patches for in-the-wild exploits: urgency can override step 3's
  "read every changelog" depth, but steps 1 and 2 still hold.
