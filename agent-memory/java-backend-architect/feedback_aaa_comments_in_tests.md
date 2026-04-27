---
name: Arrange-Act-Assert comments in tests
description: User wants every test method structured with explicit // Arrange // Act // Assert comments
type: feedback
---

Structure every test method with three explicit section comments: `// Arrange`, `// Act`, `// Assert`.

**Why:** It's the convention the user uses consistently across their tests; matching it keeps the codebase uniform and makes the intent of each block immediately readable when skimming a test file. Preference confirmed on the TicTacToe backend test suite.

**How to apply:**
- Default for any new JUnit test method.
- When act and assert collapse into one expression (e.g., `assertThatThrownBy(() -> sut.doThing(...))`), use a single `// Act + Assert` comment — don't fabricate a separate act step just to keep the triad symmetric.
- When there is nothing to arrange (e.g., the test calls a static factory directly), omit the `// Arrange` comment rather than writing `// Arrange: nothing`.
- Skip on ArchUnit-style single-expression rule checks — the `// Arrange/Act/Assert` triad has nothing to label there.
