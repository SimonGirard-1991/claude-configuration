# Architecture Tests

Enforce module boundaries and layering with code, not documentation. Without these, `package-info.java` declarations are wishful thinking.

Two approaches, pick one:
- **Spring Modulith**: zero boilerplate if you use Modulith anyway.
- **ArchUnit**: works everywhere (no Spring required), very flexible.

Using both is fine and gives belt-and-braces coverage.

---

## Contents

- Spring Modulith
- ArchUnit rules
- Multi-BC boundary rules
- Naming conventions enforced
- Constructor dependencies
- Notes
- Variants

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
import org.junit.jupiter.api.Test;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.*;

class HexagonalLayersTest {

  private static final JavaClasses APP =
      new ClassFileImporter().importPackages("com.company.ecom");

  @Test
  void domain_has_no_framework_imports() {
    noClasses()
        .that().resideInAPackage("..domain..")
        .should().dependOnClassesThat().resideInAnyPackage(
            "org.springframework..",
            "jakarta.persistence..",
            "jakarta.ws.rs..",
            "org.jooq..",
            "org.apache.kafka..",
            "com.fasterxml.jackson..",
            "tools.jackson..")
        .check(APP);
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
    noClasses()
        .that().resideInAPackage("..domain..")
        .should().haveSimpleNameEndingWith("Command")
        .check(APP);
  }

  @Test
  void commands_live_in_application_command_package() {
    classes()
        .that().haveSimpleNameEndingWith("Command")
        .should().resideInAPackage("..application.command..")
        .check(APP);
  }

  @Test
  void generated_rest_api_types_are_only_used_by_web_adapter() {
    noClasses()
        .that().resideOutsideOfPackage("..infrastructure.web..")
        .should().dependOnClassesThat().resideInAPackage("..infrastructure.web.generated..")
        .check(APP);
  }
}
```

What the last three rules are defending:

- **Commands represent external intent**, so they live in `application/`, never `domain/` — see `hexagonal-ddd-java` → "Commands live in application, not domain".
- **`commands_live_in_application_command_package` is the positive counterpart**: a `*Command` class must sit in `..application.command..`, not scattered through web or infrastructure. Name-based checks like this are cheap and catch drift early.
- **Generated OpenAPI DTOs and interfaces are web-adapter types.** The controller implements the generated interface and the web mappers reference the DTOs; nobody else should. A counterpart rule for the proto classes in `grpc-adapter.md` takes the same shape.

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
import com.company.ecom.order.application.port.OrderRepository;
import org.springframework.web.bind.annotation.RestController;

@Test
void repositories_end_with_Repository() {
  classes()
      .that().implement(OrderRepository.class)
      .should().haveSimpleNameEndingWith("Repository")
      .check(APP);
}

@Test
void controllers_live_in_web_package() {
  classes()
      .that().areAnnotatedWith(RestController.class)
      .should().resideInAPackage("..infrastructure.web..")
      .check(APP);
}
```

## Constructor dependencies

A bean takes at most seven constructor dependencies (`~/.claude/conventions/java.md` § Simplicity).
Sonar's java:S107 cannot keep this limit. It skips a constructor marked `@Autowired` or
`@Inject`, and it keeps no record of the classes that were already over, so it cannot let
them shrink step by step. The test records each bean that is over the limit today with its
exact count.

```java
// src/test/java/com/company/ecom/architecture/ConstructorDependenciesTest.java
package com.company.ecom.architecture;

import com.tngtech.archunit.core.domain.JavaClass;
import com.tngtech.archunit.core.domain.JavaClasses;
import com.tngtech.archunit.core.importer.ClassFileImporter;
import com.tngtech.archunit.core.importer.ImportOption;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.Bean;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

import static java.util.Map.entry;
import static java.util.stream.Collectors.toMap;
import static org.assertj.core.api.Assertions.assertThat;

class ConstructorDependenciesTest {

  private static final int LIMIT = 7;

  private static final Map<String, Integer> OVER_THE_LIMIT_TODAY = Map.ofEntries(
      entry("com.company.ecom.order.application.OrderService", 9));

  private static final JavaClasses APP = new ClassFileImporter()
      .withImportOption(ImportOption.Predefined.DO_NOT_INCLUDE_TESTS)
      .importPackages("com.company.ecom");

  @Test
  void only_the_recorded_beans_exceed_the_limit_and_by_their_recorded_count() {
    // Act
    List<JavaClass> beans = APP.stream()
        .filter(ConstructorDependenciesTest::isBean)
        .toList();
    Map<String, Integer> overTheLimit = beans.stream()
        .filter(bean -> dependencies(bean) > LIMIT)
        .collect(toMap(JavaClass::getName, ConstructorDependenciesTest::dependencies));

    // Assert
    assertThat(beans).isNotEmpty();
    assertThat(overTheLimit).containsExactlyInAnyOrderEntriesOf(OVER_THE_LIMIT_TODAY);
  }

  private static boolean isBean(JavaClass type) {
    return type.isMetaAnnotatedWith(Component.class)
        || type.getConstructorCallsToSelf().stream()
            .anyMatch(call -> call.getOrigin().isAnnotatedWith(Bean.class)
                && type.isAssignableTo(call.getOrigin().getRawReturnType().getName()));
  }

  private static int dependencies(JavaClass bean) {
    return bean.getConstructors().stream()
        .mapToInt(constructor -> constructor.getRawParameterTypes().size())
        .max()
        .orElse(0);
  }
}
```

The test fails until the record matches the code. That covers a new bean over the limit, a
recorded bean that grew, and one that shrank or dropped under the limit. When a bean shrinks,
lower its count or remove its entry, so the limit only tightens. The test also fails when it
finds no bean at all, so a wrong package name cannot keep it green.

A bean is a class annotated with `@Component` or anything built on it (`@Service`,
`@Repository`, `@RestController`, `@Configuration`, a custom stereotype), or a class that a
`@Bean` method constructs and returns. Its count is the parameter count of its largest constructor. Field
injection escapes the count, so pair this test with ArchUnit's
`GeneralCodingRules.NO_CLASSES_SHOULD_USE_FIELD_INJECTION`.

## Notes

- **Run as part of the regular test suite**, not separately. Architecture drift happens fastest when the check isn't in the main pipeline.
- **Fast**: ArchUnit scans compiled classes; typically <1 second even on large codebases.
- **Add rules incrementally**. A legacy codebase won't pass every rule on day one — freeze violations with `FreezingArchRule` and fail on *new* violations only.
- **A count is recorded in the test, not frozen.** `FreezingArchRule` matches a violation by its text. With the count in the message, any change to the count fails as a new violation, and only `freeze.refreeze=true` moves the record, which re-records every frozen rule in that run. Without the count in the message, a recorded class grows unseen.
- **Pair with Modulith** for its out-of-the-box "no cycles" and "allowed dependencies" checks, and use ArchUnit for everything else.

## Variants

- **Without Spring**: skip Modulith; ArchUnit covers everything. In `ConstructorDependenciesTest`, replace `Component.class` with the framework's bean annotation (`jakarta.inject.Singleton` on Micronaut, `jakarta.enterprise.context.ApplicationScoped` on Quarkus). Replace `Bean.class` with `jakarta.enterprise.inject.Produces` on Quarkus, and drop the `@Bean` clause on Micronaut. Plain Java with no container has no annotation to select beans by: select the application services by package instead.
- **Multi-module Maven/Gradle**: POM/build.gradle dependencies already enforce much of this at compile time. Use ArchUnit for intra-module rules (e.g., no framework in `domain/`).
