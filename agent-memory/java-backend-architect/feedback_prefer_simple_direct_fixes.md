---
name: Prefer simple direct fixes over elaborate defensive scripts
description: User strongly prefers minimal, straightforward solutions — complex multi-step scripts with docker exec, error handling cascades, etc. provoke frustration
type: feedback
---

When fixing infrastructure issues, prefer the simplest direct solution over elaborate defensive scripts.

**Why:** During a CDC debugging session, a register-connector.sh script was made overly complex (docker exec into containers, dropping replication slots, multi-step error handling). The user's reaction was strongly negative. The right fix was a one-line SQL command run manually + a clean simple script — not an all-in-one automated recovery procedure.

**How to apply:** When a fix involves infrastructure state (DB, Kafka, Debezium):
- Give the user the direct manual command to run, rather than wrapping everything in a script
- Keep scripts doing one thing (register the connector, not also fix every possible state issue)
- Band-aid migrations stacking on top of each other are a smell — step back and clean up instead
- If the situation is messy, recommend cleaning the state (delete flyway rows, drop slots) rather than adding more layers of defensive code
