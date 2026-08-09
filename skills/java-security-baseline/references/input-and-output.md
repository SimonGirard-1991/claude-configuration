# Input validation and output encoding

Reference for the `java-security-baseline` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

## Input validation

**Validate at every boundary. Reject early.** The boundary is any point where data enters the application from a source outside its trust zone — HTTP controllers, message consumers, webhook handlers, file uploads, admin CLIs, scheduled-job parameters.

### Bean Validation (`jakarta.validation`) on DTOs

Controllers and consumer payloads should be DTOs with Bean Validation annotations, validated with `@Valid`. This is the first line of defense and the cheapest.

```java
public record CreateAccountRequest(
    @NotBlank @Size(max = 120) String ownerName,
    @Email @Size(max = 255) String email,
    @NotNull @Positive @DecimalMax("1000000.00") BigDecimal openingBalance,
    @NotNull Currency currency
) {}

@PostMapping("/accounts")
public AccountResponse create(@Valid @RequestBody CreateAccountRequest req) { ... }
```

**Non-negotiables**:

- **Every string has a max length.** Unbounded strings are a DoS vector (memory, DB column overflow, log flooding) and an injection-payload amplifier. `@Size(max = N)` on every `String` field.
- **Every number has bounds.** `@Min`, `@Max`, `@Positive`, `@DecimalMax`. An integer overflow in a balance field is a real bug.
- **Every collection has a max size.** `@Size(max = N)` on lists. "Submit 10 million items in one request" is someone's DoS.
- **Nested objects get validated too.** `@Valid` on nested fields, or validation stops at the outer shell.
- **`@Validated` on service methods** for parameters that bypass the controller (internal calls, Kafka consumers calling use cases directly).

### Domain-level invariants are not optional

Bean Validation is a filter, not a replacement for domain invariants. A `Money` value object that rejects negative amounts in its constructor is what actually protects the system. A DTO validator that is removed in a refactor is the weakest link — the domain invariant survives.

**Where each validation lives**:

- **Syntactic shape** (length, regex, numeric bounds, required fields) → Bean Validation on DTOs.
- **Business invariants** (balance ≥ 0, account is active, transfer amount ≤ daily limit) → domain model / aggregate, enforced in the constructor or the behavior method.
- **Cross-entity consistency** (source and target accounts belong to the same customer) → use case / application service, with the domain enforcing its own half.

See `hexagonal-ddd-java` for the full layering rules.

### Rejecting unsafe content

- **HTML / Markdown / rich text**: run through an allowlist sanitizer (OWASP Java HTML Sanitizer) before storage. Never store raw HTML from an untrusted source.
- **File uploads**: validate content type by sniffing magic bytes, not by trusting `Content-Type` or filename extension. Enforce max file size at the framework level (`spring.servlet.multipart.max-file-size`) *and* at the reverse proxy.
- **XML**: disable external entity resolution (XXE). `XMLInputFactory.IS_SUPPORTING_EXTERNAL_ENTITIES = false`, `SUPPORT_DTD = false`. Prefer JSON where you have the choice.
- **YAML**: use SnakeYAML's `SafeConstructor` or a `LoaderOptions` with `setAllowDuplicateKeys(false)` — unsafe YAML has historically been an RCE vector.
- **Regex from untrusted input**: catastrophic backtracking (ReDoS) is a real DoS vector. Use a timeout-bounded matcher or reject patterns before compiling.

## Output encoding and parameterized queries

### SQL — parameterize, always

- **jOOQ**: parameterization is the default. `dsl.selectFrom(USERS).where(USERS.EMAIL.eq(email))` binds the parameter. **Never** use `DSL.inline(userInput)` on untrusted data — that is string concatenation with a nicer name.
- **Plain JDBC**: `PreparedStatement` with `?` placeholders. Never `Statement.executeQuery("SELECT ... WHERE id = " + id)`. Ever.
- **Spring Data JPA / Spring JDBC**: `@Query` with named parameters. Never use SpEL to interpolate user input into a JPQL/SQL string.
- **Dynamic queries**: build them with the query builder (jOOQ DSL, Criteria API), not with string concatenation. If you must concatenate (e.g., dynamic `ORDER BY` column name), validate against an allowlist of known column names first.

**Review red flag**: any `+` operator between SQL text and a variable. Any `String.format` building SQL. Any `"WHERE " + column + " = ?"` where `column` came from input without an allowlist check.

### HTML / JSON output

- **HTML templates** (Thymeleaf, JTE, Mustache): default to context-aware escaping. Verify your template engine escapes by default in the expression syntax you are using (e.g., Thymeleaf's `th:text` escapes, `th:utext` does not). Flag every `utext` / raw output in review.
- **JSON**: Jackson's default behavior is safe. Do not write JSON with string concatenation. Do not enable `ObjectMapper.enableDefaultTyping()` on data from untrusted sources — it has been an RCE vector repeatedly.
- **Response headers**: set `Content-Type` explicitly. Content sniffing combined with a permissive type has been an XSS vector.

### Logging and error messages

- **Never log raw user input as a format string.** `log.info(userInput)` is a log-forging / format-string bug. Use `log.info("request from {}", userInput)` — parameterized.
- **Error responses** should not leak stack traces, internal paths, SQL, or framework internals to external callers. Spring Boot's default error handler does; override it in production profiles.
- **Never include raw input in error messages** echoed to the caller when the input could contain HTML/JS (reflected XSS) or control characters (log forging downstream).

### Security headers

For any HTTP service, set these at the framework or gateway layer:

- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (HTTPS only)
- `Content-Security-Policy` — restrictive, deny by default
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY` (or CSP `frame-ancestors`)
- `Referrer-Policy: strict-origin-when-cross-origin`
- Remove `Server` / `X-Powered-By` disclosures.

Spring Security adds most of these by default; verify they are enabled in the deployed profile.
