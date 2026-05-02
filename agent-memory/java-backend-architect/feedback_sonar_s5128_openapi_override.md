---
name: S5128 false positive on OpenAPI-generated controller overrides
description: Don't blindly add @Valid to controller method overrides — Hibernate Validator's HV000151 hard-fails when the parent interface already declares @Valid. Use @SuppressWarnings instead.
type: feedback
---

Sonar S5128 ("Add missing @Valid …") is a **false positive** on
controller methods that override an OpenAPI-generated API interface.
Do **not** add `@Valid` to the override.

**Why:** Hibernate Validator enforces JSR-380's "covariant
precondition" rule via `HV000151` — *"A method overriding another
method must not redefine the parameter constraint configuration."*
The OpenAPI Generator emits `@Valid @RequestBody DtoType dto` on the
interface method; if the override re-declares `@Valid`, validation
hard-fails at request time with a 500 (caught by the global exception
handler) — even though the annotations are *semantically* identical.
Spring MVC already validates the body at runtime via the interface's
`@Valid`, so the override needs nothing.

**How to apply:**

- For controller methods that `@Override` a generated API interface
  method, suppress the rule rather than fix it:

  ```java
  @Override
  public ResponseEntity<Foo> create(
      UUID id,
      UUID transactionId,
      @SuppressWarnings("java:S5128") CreateFooRequestDto dto) { … }
  ```

- For mappers / non-controller beans, `@Valid` on a parameter is
  silently dead unless the class is `@Validated`. Adding it to please
  Sonar is harmless; arguably better to suppress with rationale, but
  picking either is fine — prefer minimum diff.

- The Hibernate Validator rule can technically be loosened with
  `allowOverridingMethodAlterParameterConstraint(true)`, but that is a
  global config change with broad LSP implications — don't reach for
  it just to silence Sonar.

**Detection signature:** a 500 from a controller test, with stack
mentioning `jakarta.validation.ConstraintDeclarationException:
HV000151` and `redefines the configuration of <Api>#<method>`.
