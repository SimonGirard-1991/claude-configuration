# Code comments

- **The default is none.** Comments are for the next developer who reads the code, so one earns its place only when the code cannot carry the information — a non-obvious constraint, a rejected alternative, an external quirk, an invariant a reader would otherwise break. Never restate what the code already says.
- If a comment is needed to explain *what* the code does, that's a bug report about the code: rename, extract, or split, then drop the comment. Doc comments (Javadoc/TSDoc/docstrings) are held to the same bar; `--help` text and script header blocks are user-facing documentation and stay.
- A comment that stays is written in plain sentences: a subject and a verb, one idea per sentence. If a sentence needs a second reading, rewrite it.
- **Exception — tests.** Each test method (JUnit, Jest/Vitest) marks its phases with `// Arrange`, `// Act`, `// Assert`. Use `// Act + Assert` when one expression does both, and leave out `// Arrange` when nothing is arranged. No markers on single-expression rule checks (ArchUnit). In a repo whose tests already label phases with comments in another vocabulary (`// given` / `// when` / `// then`), use that vocabulary; blank-line spacing or BDD-named APIs are not a marking convention.
- Explanation of a change belongs in the reply and the commit message, not in the file.

# Working style

- In the main session, enter plan mode for complex multi-step work and get the plan approved before editing. A subagent works from the plan its caller gave it (subagents cannot enter plan mode).
- Commits: a one-line conventional subject (`feat:`, `fix:`, `chore:`); add a body only for what the diff cannot show.
- **Bound what Bash prints.** Read a file you may edit with Read, not `cat`: Edit refuses a file Read has not seen, so `cat` first means reading it twice. Otherwise read only the part you need: find it with `grep -n`, then a `sed -n` range or Read with offset/limit. Send builds and test runs to a log in `$TMPDIR`, then print the exit code and the failures or the tail.

# This machine

- Before concluding Docker is down, check Docker Desktop's specifics: the socket is `~/.docker/run/docker.sock` (context `desktop-linux`; `/var/run/docker.sock` does not exist here), and `docker-credential-desktop` lives in `/Applications/Docker.app/Contents/Resources/bin`, which a non-interactive shell's PATH lacks, so pulls fail on credentials. Right after launch the engine answers 500 until its VM is up: poll `docker version` for a Server version.
