# Dependency hygiene and unsafe deserialization

Reference for the `java-security-baseline` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

## Dependency hygiene

- **OWASP Dependency-Check or Snyk in CI.** The build fails on new `CRITICAL` / `HIGH` CVEs in direct or transitive dependencies. A PR that introduces a vulnerable dependency gets blocked; a nightly scan flags newly-disclosed CVEs in existing dependencies.
- **Renovate or Dependabot** for automated dependency PRs. Small frequent updates are safer than rare giant ones.
- **Pin to versions, not ranges.** `implementation("org.example:lib:1.2.3")`, not `1.2.+`. Reproducible builds matter.
- **Lockfile in VCS**: `gradle.lockfile` / `pom.xml` with explicit versions of transitives. A new CVE in a transitive you did not know you had is worse than one in a direct dependency.
- **SBOM** (CycloneDX, SPDX) published per release. When a CVE drops, "which of our services has this?" is answered in minutes, not hours.
- **Signed artifacts**: publish and verify with Sigstore / GPG. Supply-chain attacks are no longer hypothetical.
- **Scope the classpath**: runtime dependencies are not compile-time dependencies. `runtimeOnly`, `testImplementation`, `compileOnly` — the smaller the production classpath, the smaller the attack surface.

**Known-bad patterns to refuse**:

- `log4j-core < 2.17.1` (Log4Shell).
- `jackson-databind` with default typing enabled on untrusted input.
- `commons-collections 3.x` with `InvokerTransformer` reachable on a deserialization path.
- Unmaintained libraries with open CVEs and no fix. Replace, do not patch around.

## Unsafe deserialization

Deserializing untrusted bytes into objects has been an RCE vector for a decade. Rules:

- **Never `ObjectInputStream.readObject` on untrusted input.** Java serialization is unsafe by design.
- **Never enable default typing on a Jackson `ObjectMapper` that processes untrusted JSON.** `enableDefaultTyping()` / `activateDefaultTyping()` are RCE vectors.
- **Never use XMLDecoder, XStream without a typed allowlist, or any deserializer that reconstructs arbitrary types from a type hint in the payload.**
- **Prefer data-only formats**: plain JSON with explicit target types, Protobuf, Avro. These do not reconstruct arbitrary classes.
