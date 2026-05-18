---
name: Repo-grounded but generalizable docs
description: When the user asks for a doc on something they did in a repo, they want both the specific war stories AND transferable principles, without being limited to repo references.
type: feedback
---

When asked to document a project the user did in a specific repository, they want the doc to
be *grounded* in the repo's real material (read the runbook, the ADRs, the code) but not
*limited* to it. The end-product can speak in general terms suitable for someone unfamiliar
with the project. Cite the specific gotchas the project surfaced as worked subtleties, but
frame them as transferable lessons.

**Why:** the doc serves as both interview-prep (where generality wins) and as a personal
write-up of the war story (where specificity wins). The user explicitly said "the final
doc is not mandatory to refer directly to this repository" — meaning: extract the
principle, drop the repo-noise unless it sharpens the principle.

**How to apply:** read all the source material thoroughly first. Then write so a stranger
could follow without ever having seen the codebase, while still preserving 4-6 concrete
worked subtleties drawn from the real execution. File paths and line numbers are fine
when they make a point land harder; gratuitous repo-internal references are not.
