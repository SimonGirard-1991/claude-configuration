# Architecture Tests

Enforce module boundaries and layering with code, not documentation. Without these, `package-info.java` declarations are wishful thinking.

Two approaches, pick one:
- **Spring Modulith**: zero boilerplate if you use Modulith anyway.
- **ArchUnit**: works everywhere (no Spring required), very flexible.

Using both is fine and gives belt-and-braces coverage.

---

## Spring Modulith

```java
// src/test/java/com/company/ecom/ModuleBoundariesTest.java
package com.company.ecom;

import com.company.ecom.EcomApplication;
import org.junit.jupiter.api.Test;
import org.springframework.modulith.core.ApplicationModules;

class ModuleBoundariesTest {

  @Test
  void modulesRespectBoundaries() {
    ApplicationModules.of(EcomApplication.class).verify();
  }
}
```

This asserts:
- Each `@ApplicationModule`'s `allowedDependencies` is respected.
- No circular dependencies between modules.
- `CLOSED` modules are not imported outside their allowed consumers.
- Public `@NamedInterface` packages are the only cross-BC entry points.

## ArchUnit rules

```java
// src/test/java/com/company/ecom/architecture/HexagonalLayersTest.java
package com.company.ecom.architecture;

import com.tngtech.archunit.core.domain.JavaClasses;
import com.tngtech.archunit.core.importer.ClassFileImporter;
import com.tngtech.archunit.lang.ArchRule;
import org.junit.jupiter.api.Test;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.*;

class HexagonalLayersTest {

  private static final JavaClasses APP =
      new ClassFileImporter().importPackages("com.company.ecom");

  @Test
  void domain_has_no_framework_imports() {
    ArchRule rule = noClasses()
        .that().resideInAPackage("..domain..")
        .should().dependOnClassesThat().resideInAnyPackage(
            "org.springframework..",
            "jakarta.persistence..",
            "jakarta.ws.rs..",
            "org.jooq..",
            "org.apache.kafka..",
            "com.fasterxml.jackson..");
    rule.check(APP);
  }

  @Test
  void application_does_not_depend_on_infrastructure() {
    noClasses()
        .that().resideInAPackage("..application..")
        .should().dependOnClassesThat().resideInAPackage("..infrastructure..")
        .check(APP);
  }

  @Test
  void infrastructure_does_not_leak_to_domain() {
    noClasses()
        .that().resideInAPackage("..domain..")
        .should().dependOnClassesThat().resideInAPackage("..infrastructure..")
        .check(APP);
  }

  @Test
  void commands_do_not_live_in_domain() {
    // Commands represent external intent and live in application/, not domain/.
    // See hexagonal-ddd-java → "Commands live in application, not domain".
    noClasses()
        .that().resideInAPackage("..domain..")
        .should().haveSimpleNameEndingWith("Command")
        .check(APP);
  }

  @Test
  void commands_live_in_application_command_package() {
    // Positive counterpart to the rule above: a class named *Command must live in
    // ..application.command.. — not scattered in web, infrastructure, or elsewhere.
    // Name-based checks like this are cheap and catch drift early.
    classes()
        .that().haveSimpleNameEndingWith("Command")
        .should().resideInAPackage("..application.command..")
        .check(APP);
  }

  @Test
  void generated_rest_api_types_are_only_used_by_web_adapter() {
    // Generated OpenAPI DTOs and interfaces are web-adapter types. They must not leak
    // into application/ or domain/. The controller implements the generated interface
    // and the web mappers reference the DTOs — nobody else should.
    // Counterpart rule for proto classes in grpc-adapter.md would follow the same shape.
    noClasses()
        .that().resideOutsideOfPackage("..infrastructure.web..")
        .should().dependOnClassesThat().resideInAPackage("..infrastructure.web.generated..")
        .check(APP);
  }
}
```

## Multi-BC boundary rules

```java
// src/test/java/com/company/ecom/architecture/BoundedContextBoundariesTest.java
class BoundedContextBoundariesTest {

  private static final JavaClasses APP =
      new ClassFileImporter().importPackages("com.company.ecom");

  @Test
  void order_BC_only_imports_billing_via_api_package() {
    noClasses()
        .that().resideInAPackage("..order..")
        .should().dependOnClassesThat().resideInAnyPackage(
            "..billing.domain..",
            "..billing.application..",
            "..billing.infrastructure..")
        .check(APP);
  }

  @Test
  void no_direct_imports_across_BC_domains() {
    noClasses()
        .that().resideInAPackage("com.company.ecom.order.domain..")
        .should().dependOnClassesThat().resideInAnyPackage(
            "com.company.ecom.billing..",
            "com.company.ecom.catalog..",
            "com.company.ecom.shipping..")
        .check(APP);
  }
}
```

## Naming conventions enforced

```java
@Test
void repositories_end_with_Repository() {
  classes()
      .that().implement(com.company.ecom.order.application.port.OrderRepository.class)
      .should().haveSimpleNameEndingWith("Repository")
      .check(APP);
}

@Test
void controllers_live_in_web_package() {
  classes()
      .that().areAnnotatedWith(org.springframework.web.bind.annotation.RestController.class)
      .should().resideInAPackage("..infrastructure.web..")
      .check(APP);
}
```

## Notes

- **Run as part of the regular test suite**, not separately. Architecture drift happens fastest when the check isn't in the main pipeline.
- **Fast**: ArchUnit scans compiled classes; typically <1 second even on large codebases.
- **Add rules incrementally**. A legacy codebase won't pass every rule on day one — freeze violations with `FreezingArchRule` and fail on *new* violations only.
- **Pair with Modulith** for its out-of-the-box "no cycles" and "allowed dependencies" checks, and use ArchUnit for everything else.

## Variants

- **Without Spring**: skip Modulith; ArchUnit covers everything.
- **Multi-module Maven/Gradle**: POM/build.gradle dependencies already enforce much of this at compile time. Use ArchUnit for intra-module rules (e.g., no framework in `domain/`).
