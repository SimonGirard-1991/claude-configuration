---
name: Mockito annotations over manual mock() calls
description: User prefers @ExtendWith(MockitoExtension.class) + @Mock + @InjectMocks over manual mock() calls in JUnit 5 tests
type: feedback
---

In JUnit 5 tests, prefer `@ExtendWith(MockitoExtension.class)` at class level with `@Mock` on fields and `@InjectMocks` on the SUT, over hand-written `mock(X.class)` assignments in `@BeforeEach`.

**Why:** Simpler and less verbose. Fewer lines of ceremony per test class, constructor wiring is automatic, and it reads more declaratively. Preference confirmed on the TicTacToe backend test suite.

**How to apply:**
- Default to annotation-driven Mockito for any new use-case / service test that depends only on mocks.
- `@BeforeEach` stays only for stubbing that can't be declared on the mock fields (e.g., `when(...).thenReturn(...)` chains that depend on fixture values) — not for `x = mock(X.class)` boilerplate.
- Don't switch if the test uses real collaborators mixed with mocks in a way that `@InjectMocks` can't resolve — pick the approach that minimizes ceremony in that specific file.
- Fakes (in-memory implementations) are still preferred over mocks for ports with useful in-memory shapes — this feedback is about *how* to wire mocks *when* mocks are the right call, not about mocks vs. fakes.
