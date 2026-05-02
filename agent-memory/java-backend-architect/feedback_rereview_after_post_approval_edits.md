---
name: Re-review after any post-approval code edit
description: Even when a reviewer's ✅ verdict was conditional on a suggestion the user/me chose to apply, the resulting diff is new code the reviewer hasn't seen — re-invoke for iteration N+1
type: feedback
---

After a `code-reviewer` verdict of ✅, do NOT modify the code and then commit without re-invoking the reviewer. The verdict applies to the diff the reviewer saw — if you apply one of their 🔵 suggestions verbatim, push back on another, or otherwise touch the file, the resulting code is a NEW diff that has not been verified.

The reviewer is not a suggestion box. It is a verification gate. Treating its suggestions as "free to apply without re-checking" turns it into a rubber stamp.

**Why:** User caught me cutting this corner on the Wealthpay observability work (commit 1: replication-slot collector). I applied a CTE refactor the reviewer had suggested verbatim and pushed back on a help-text-length suggestion, then went straight to commit. User's correction: "but you modify code after review, you don't call it back again?" Two real risks I had glossed over: (1) the reviewer wrote the suggestion as a standalone snippet and never saw it integrated into the surrounding comments and file structure; (2) my pushback on the second suggestion was undefended in writing — it could have been a flawed line of reasoning that the reviewer would have caught on a second pass.

**How to apply:**
- After ✅, if the diff is unchanged → commit, that's what ✅ is for.
- After ✅, if you apply ANY 🔵 suggestion or push back on one with reasoning the reviewer hasn't seen → re-invoke. This is iteration 2 of the 3-iteration cap, exactly what the cap budget exists for.
- The re-invocation prompt MUST: (a) name what you applied verbatim, (b) name what you declined with the reasoning, (c) explicitly invite the reviewer to either accept the pushback or surface a reason the reasoning is wrong. Asking "do you accept?" closes the loop in writing.
- The cost-awareness clause ("don't invoke after every micro-edit") does not apply here. Applying a reviewer's own suggestion is not a micro-edit from the protocol's perspective; it is a checkpoint where verification has lapsed.
- The 3-iteration cap still bites. Don't loop endlessly on style nits. If iteration 3 still has unresolved 🔵s, hand to the user with both positions stated.
