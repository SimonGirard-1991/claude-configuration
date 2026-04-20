---
name: Always re-check git state before every review
description: Before any code review, inspect the current git repository state fresh — do not rely on prior-turn snapshots or system-reminder diffs.
type: feedback
---

Before producing a code review, always run `git status --short` and `git diff` (staged + unstaged as appropriate) at that moment, and `Read` the actual files. Do not assume the git status snippet from the conversation's system reminder is current.

**Why:** User explicitly asked "Check the actual state of git repository each time you have to do a review." Conversation-start snapshots can drift within the same session (files staged/unstaged, new files appear), and a review based on a stale snapshot misses or misattributes changes.

**How to apply:** Open every review by fetching the live state (`git status`, `git diff`, `git diff --staged`) and reading the referenced files directly. Only then form the review. Applies for every review request, even follow-up reviews in the same conversation.

**Specific trap to avoid — content claims from diff display.** When a diff contains very long single lines (e.g. Grafana JSON where one `description` field is 1–3 KB, one-line SQL strings, one-line YAML arrays), terminal diff display can visually truncate or wrap the `+`/`-` line such that the tail is easy to miss. Asserting "X is missing from the new version" based on the diff alone is unsafe in these cases. Rule: for any claim of the form "the new version dropped content Y," verify by `Grep`ing for a substring of Y in the live file before stating it. Failure mode observed: three of four "Important" issues in a dashboard-descriptions review were false claims of dropped content that was actually present at the tail of long `+` lines. Cost: three review rounds chasing non-issues.
