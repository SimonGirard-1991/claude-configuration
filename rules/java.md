---
# The contract globs are deliberate: a schema change is a code change, and the file
# being edited is the schema, so a **/*.java scope alone would miss it.
paths:
  - "**/*.java"
  - "**/pom.xml"
  - "**/build.gradle"
  - "**/build.gradle.kts"
  - "**/*.avsc"
  - "**/*.avdl"
  - "**/*.proto"
  - "**/openapi/**"
  - "**/openapi*.yaml"
  - "**/openapi*.yml"
  - "**/*-api.yaml"
  - "**/*-api.yml"
---
[rule-stub java] The user's Java conventions are in ~/.claude/conventions/java.md. If no [session-rules java …] block is already in context, read that file before planning, editing or reviewing Java code or its contract files.
