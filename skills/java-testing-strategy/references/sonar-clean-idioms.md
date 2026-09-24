# Test idioms Sonar rejects

Reference for the `java-testing-strategy` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

## Why these three

A SonarQube scan of a Spring Boot + jOOQ backend (178 files, 5,268 ncloc, ~3.5 months of
agent-written Java) returned 31 issues. Zero bugs, zero vulnerabilities, zero hotspots — all
code smells, and **23 of the 31 were in `*Test.java`**. Three rules accounted for 22 of those.

They are not defects. They are the same three habits repeated across every test class written
in that period, which is what makes them worth stating once rather than fixing 22 times.

Note what does *not* catch them: Error Prone, SpotBugs, PMD and Checkstyle have no equivalent
for any of the three. They are JUnit- and Mockito-aware rules that only Sonar's own analyzers
implement, so a local lint stack reports green on all 22.

## `java:S5778` — one throwing call per `assertThrows` (14 of 31)

The lambda must contain exactly one invocation that can throw, or the assertion cannot say
which call produced the exception — a passing test that proves the wrong thing.

```java
// rejected: three calls in the lambda, any of which could throw
assertThrows(IllegalStateException.class, () -> {
    var customer = Customer.reconstitute(id, name);
    customer.activate(clock);
    customer.activate(clock);
});
```

```java
// accepted: setup outside, one call under assertion
// Arrange
var customer = Customer.reconstitute(id, name);
customer.activate(clock);

// Act + Assert
assertThrows(IllegalStateException.class, () -> customer.activate(clock));
```

Move every line that is arrange rather than act out of the lambda. When two calls genuinely
both need asserting, that is two tests.

## `java:S9015` — `@Mock` fields, not `mock()` (6 of 31)

Under `@ExtendWith(MockitoExtension.class)`, a field initialised with `Mockito.mock()` is
outside Mockito's lifecycle: it is not reset between tests, and strict-stub checking never
sees it. Sonar flags the field declaration, so one class with six collaborators produces six
findings at once.

```java
@ExtendWith(MockitoExtension.class)
class AccountApplicationServiceTest {
    private final AccountStore store = mock(AccountStore.class);        // rejected
    private final EventPublisher publisher = mock(EventPublisher.class); // rejected
```

```java
@ExtendWith(MockitoExtension.class)
class AccountApplicationServiceTest {
    @Mock private AccountStore store;
    @Mock private EventPublisher publisher;
    @InjectMocks private AccountApplicationService service;
```

Applies to fields only. A `mock()` call inside a test method is fine, and is still the right
tool for a one-off stub. Whether to mock at all is a separate question — `SKILL.md` and
`layers-domain-application.md` own that.

## `java:S5853` — chain assertions on one subject (2 of 31)

Consecutive `assertThat` calls on the same subject should be one chain, so a failure reports
every unmet expectation instead of stopping at the first.

```java
// rejected
assertThat(config.getSchemas()).hasSize(2);
assertThat(config.getSchemas()).contains("account");
```

```java
// accepted
assertThat(config.getSchemas()).hasSize(2).contains("account");
```

This narrows the existing guidance in `layers-domain-application.md`: chaining on *one*
subject is required, while asserting on three unrelated subjects is still two or three tests.

## When Sonar is wrong

These rules are worth following, and none of them is worth contorting real code for. When a
finding does not apply, suppress it with the reason on the same line — a bare suppression is
refused by the gate, and `@SuppressWarnings("all")` always is:

```java
@SuppressWarnings("java:S5778") // both calls must throw inside one transaction to reproduce
```

Report every suppression you add when handing work back. Suppressing is a decision the user
should see, not a way to reach green.

## Keeping this list honest

Three rules are what one codebase produced in one period; a different codebase produces a
different three. `scripts/sonar-gate.sh --facets` prints the current rule-frequency
distribution for a project. When a rule starts appearing repeatedly and is not documented
here, add it — and when one stops appearing, it has been learned and can go.
