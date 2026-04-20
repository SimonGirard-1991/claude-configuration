---
name: No reserved Java keywords in variable names
description: Never use Java reserved keywords (e.g. record, class, default) as variable names
type: feedback
---

Do not use reserved Java keywords as variable names — e.g. `record`, `class`, `default`, `switch`, etc.

**Why:** `record` became a restricted identifier in Java 16+. Even where the compiler allows it contextually, it's confusing and risks breakage. The user explicitly flagged this.

**How to apply:** When naming local variables, parameters, or fields, avoid any Java reserved keyword or restricted identifier. Use a descriptive domain name instead (e.g. `row`, `entry`, `result`, `snapshot`).
