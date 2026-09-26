# Shell conventions

A script kept and re-run has two users: the author six months out, and possibly the
public. "It's just a personal script" never justifies skipping quoting, error handling
or a `--dry-run` — personal scripts run against personal data, the data with no backup
team behind it. Industry-grade means correct, safe, portable and self-explanatory, not
large: a 30-line wrapper gets no test suite. A task that is one obvious command with
flags is not a script — give the command instead.

## The four hard rules
- **shellcheck-clean, zero blanket disables.** Every `# shellcheck disable=` carries an
  inline justification. `shfmt -i 2 -ci -d` clean. If either tool is missing, stop and
  ask for it (`brew install shellcheck shfmt`) — never skip the gate silently.
- **`set -euo pipefail`**, applied with understanding rather than cargo-culted: `set -e`
  is disabled inside conditionals and command substitution can mask exit codes. Handle
  *expected* failures explicitly (`if ! cmd; then`); reserve strict mode for the
  unexpected. Shebang `#!/usr/bin/env bash`.
- **`--dry-run` is mandatory on anything that mutates state**, printing exactly what
  would happen. Destructive operations additionally need confirmation or an explicit
  `--force`/`--yes`. Never delete through an unvalidated variable: validate non-empty
  *and plausible* (`[[ -n "$dir" && "$dir" == "$HOME"/* ]]`) before any destructive
  expansion.
- **No hardcoded personal paths, usernames, hostnames or emails**, and no secrets in
  source or argv (argv is visible in `ps`). Parameters with env-var defaults
  (`"${DOTFILES_DIR:-$HOME/dotfiles}"`), XDG conventions, Keychain for secrets.

**Claude Code hooks** pin `#!/bin/bash` (Python hooks: `/usr/bin/python3`) and map each
failure to an explicit exit code instead of `set -euo pipefail`, because the exit code is
the interface: 0 passes, 2 blocks, and anything else does not block on its own, so a
crashing guard fails open. In a hook, 2 never means a usage error. A hook has no `--help` or `--dry-run`;
its fixture run is the execution before hand-back. MCP wrappers pin the shebang too but
keep strict mode. The rest of this file applies.

## Portability
macOS `/bin/bash` is 3.2: no `mapfile`, no associative arrays, no `${var^^}`. Write to
that floor unless the target is known to be Linux, where bash 4+/5 idioms are fair game.
Minimal images may have no bash at all — POSIX `#!/bin/sh` there; shellcheck follows the
shebang. When you cannot verify a flag or tool exists on the target, check rather than
assume. The Bash tool itself runs zsh: verify a bashism with `bash -c '…'` or through the
script's own shebang, never inline, because zsh reads a leading `0` as decimal and other
bashisms differ too. Before writing a new script, check `~/.local/bin` for a personal
tool that already does the job, and extend it rather than add a near-duplicate.

## Zsh is not bash
Never run shellcheck on zsh files — it does not support the language. The gate is
`zsh -n <file>` plus a fresh `zsh -i -c exit` starting clean. Unquoted parameters do not
word-split, arrays are 1-indexed, and non-matching globs error. Write native zsh; do not
impose bash idioms or "fix" zsh for bash problems it cannot have. Optimization is
profile-first: no change without `zprof` or `time zsh -i -c exit` before/after numbers.

## Before hand-back
Every script is executed at least once — `--help`, plus a `--dry-run` or a fixture run.
Never delivered on lint alone. stdout is data, stderr is diagnostics; exit 0 success,
1 runtime failure, 2 usage error.
