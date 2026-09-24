#!/usr/bin/env python3
"""Fixture tests for the hook scripts in hooks/, and for scripts/sonar-gate.sh, whose
answer the Sonar Stop hook remembers.

Each hook runs as a subprocess on a crafted payload, the way Claude Code calls it,
and the suite asserts what it prints. The tables pin behaviour in both directions:
what a hook must catch, and what it must let through untouched, because a guard
that fires on ordinary commands teaches the session to route around it.

Hook paths come from environment overrides, so a candidate can be tested before it
replaces the live file — a broken live guard gates the very session editing it:
CLAUDE_BASH_GUARD, CLAUDE_REVIEWER_GUARD, CLAUDE_SESSION_RULES, CLAUDE_LOG_INSTRUCTIONS,
CLAUDE_SONAR_GATE_HOOK, CLAUDE_SONAR_GATE, CLAUDE_VALIDATE_README.

Run: python3 scripts/test_hooks.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASH_GUARD = os.environ.get("CLAUDE_BASH_GUARD", str(ROOT / "hooks" / "bash-guard.py"))
REVIEWER_GUARD = os.environ.get("CLAUDE_REVIEWER_GUARD", str(ROOT / "hooks" / "reviewer-guard.py"))
SESSION_RULES = os.environ.get("CLAUDE_SESSION_RULES", str(ROOT / "hooks" / "session-rules.sh"))
LOG_INSTRUCTIONS = os.environ.get("CLAUDE_LOG_INSTRUCTIONS",
                                  str(ROOT / "hooks" / "log-instructions.sh"))
SONAR_HOOK = os.environ.get("CLAUDE_SONAR_GATE_HOOK",
                            str(ROOT / "hooks" / "sonar-gate-on-stop.sh"))
SONAR_GATE = os.environ.get("CLAUDE_SONAR_GATE", str(ROOT / "scripts" / "sonar-gate.sh"))
VALIDATE_README = os.environ.get("CLAUDE_VALIDATE_README",
                                 str(ROOT / "hooks" / "validate-readme.sh"))
HOOK_OUTPUT_CAP = 9800

_passes = 0
_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global _passes
    if ok:
        _passes += 1
    else:
        _failures.append(f"{name}: {detail}" if detail else name)


def run_hook(hook, payload, env: dict | None = None,
             cwd: Path | None = None) -> subprocess.CompletedProcess:
    argv = [hook] if isinstance(hook, str) else list(hook)
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(argv, input=data, capture_output=True, text=True,
                          timeout=30, env=env, cwd=cwd, check=False)


def decision(proc: subprocess.CompletedProcess) -> str:
    if proc.returncode != 0:
        return f"exit {proc.returncode}"
    out = proc.stdout.strip()
    if not out:
        return "none"
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


# ── bash-guard.py ───────────────────────────────────────────────────────────
BASH_GUARD_CASES = {
    "ask": [
        "cat .env",
        "diff .env.example .env",
        "cat .env.example .env",
        "cp .env.example .env && cat .env",
        "cat .env>out.txt",
        "cat<.env",
        "cat .env.test.local",
        "cat .env.example.local",
        "python3 -c \"print(open('.env').read())\"",
        "ls ~/.ssh/",
        "git push origin +main",
        "git push origin :feature",
        "git push -uf origin main",
        "git push --force origin main",
        "git push --force --force-if-includes",
        "git push origin --delete feature",
        "git push --mirror",
        "git push --force-with-lease --mirror",
        "git -C repo push --force",
        "git status && git push -f",
        "git reset --hard HEAD~1",
        "git clean -fd",
        "rm -rf .",
        "rm -rf ./",
        "rm -rf ./*",
        'rm -rf "$PWD"',
        "rm -rf ${PWD}",
        "rm -rf .git",
    ],
    "deny": [
        "printenv",
        "env | grep KEY",
        "cd /tmp\nenv",
        'echo "$ANTHROPIC_API_KEY"',
        "printenv GITHUB_TOKEN",
        "echo $SSH_AUTH_SOCK",
        "security find-generic-password -s BRAVE_API_KEY -w",
        "gh auth token",
        "rm -rf ~/",
        "rm -rf /",
        'rm -rf "$HOME"',
        "rm -rf /Users",
        "rm -rf --no-preserve-root /tmp/x",
        "cat .env; rm -rf ~",
    ],
    "none": [
        "cat .env.example",
        "cp .env.example .env.sample",
        "set -euo pipefail",
        "env FOO=1 make build",
        "printenv PATH",
        "echo $GIT_AUTHOR_NAME",
        "git push origin main",
        "git push -u origin feature",
        "git push --force-with-lease origin main",
        "git push --force-if-includes origin main",
        "git push --dry-run --force",
        "git log --oneline | head -5",
        "git status --short",
        "git clean -n",
        "rm -rf dist\ngit add .",
        "rm -rf build\ncd ..",
        "rm -rf dist&&git status",
        "rm -rf node_modules",
        "rm -rf ./node_modules",
        "rm -rf .github",
        "ls -la",
        # Known gap, pinned so a change is deliberate: a secret read that names no
        # file. The Bash sandbox's denyRead is the layer meant to catch it.
        "grep -r API_KEY .",
    ],
}


def test_bash_guard() -> None:
    for expected, commands in BASH_GUARD_CASES.items():
        for cmd in commands:
            got = decision(run_hook(BASH_GUARD, {"tool_input": {"command": cmd}}))
            check(f"bash-guard {cmd!r}", got == expected, f"expected {expected}, got {got}")
    proc = run_hook(BASH_GUARD, "not json")
    check("bash-guard: an unreadable payload exits 1 and says so",
          proc.returncode == 1 and proc.stderr.strip() != "",
          f"exit {proc.returncode}, stderr {proc.stderr.strip()!r}")
    got = decision(run_hook(BASH_GUARD, {"tool_input": {}}))
    check("bash-guard: a payload without a command has no opinion", got == "none", got)


# ── reviewer-guard.py ───────────────────────────────────────────────────────
# Relative paths resolve against the repo root (the hook runs with cwd=ROOT), which
# stands in for "the repo under review". $TMPDIR is a fixture directory.
REVIEWER_BASH_CASES = {
    "none": [
        "git status --short",
        "git stash list",
        "git log --grep=commit --oneline",
        "git -C some/dir diff",
        "git --no-pager log -5",
        "git show HEAD:README.md",
        "git branch -a",
        "git branch --contains abc123",
        "git tag -l",
        "git config --get user.name",
        "git config user.name",
        "git remote -v",
        "git reflog -n 5",
        "git worktree list",
        "grep -rn git .",
        "mvn -q test",
        "npm test 2>&1 | tail -20",
        "echo done > /dev/null",
        "git diff > $TMPDIR/review.patch",
        "mkdir -p $TMPDIR/scratch && echo x > $TMPDIR/scratch/a.txt",
        "rm -f $TMPDIR/scratch/a.txt",
        "sed -n '1,20p' README.md",
        "perl -ne 'print if /x/' README.md",
        "gh pr view 12 --json title",
        "gh -R owner/repo pr diff 12",
        "gh run list",
        "env GIT_PAGER=cat git log -1",
        "timeout 60 mvn -q verify",
    ],
    "deny": [
        "git commit -m x",
        "git -C some/dir commit -m x",
        "git -c alias.x=!sh x",
        "git ci -m x",
        "git stash",
        "git fetch origin",
        "git push",
        "git checkout main",
        "git branch -D old",
        "git branch newbranch",
        "git tag v1.0",
        "git config user.name someone",
        "git remote add upstream url",
        "git diff --output=out.patch",
        "sed -i 's/a/b/' README.md",
        "perl -pi -e 's/a/b/' README.md",
        "echo x > src/A.java",
        "echo x >> README.md",
        "git diff | tee README.md",
        "vim README.md",
        'eval "git commit -m x"',
        "bash -c 'git commit -m x'",
        "xargs sed -i 's/a/b/'",
        "gh pr merge 12",
        "gh api repos/o/r/pulls",
        "rm -rf src",
        "cp README.md docs/README.md",
        "touch newfile.txt",
        "mvn -q test && git add -A",
    ],
}


def test_reviewer_guard() -> None:
    tmp = Path(tempfile.mkdtemp()).resolve()
    env = {**os.environ, "TMPDIR": str(tmp)}
    memory = Path.home() / ".claude" / "agent-memory"
    fake_scratch = ROOT / "logs" / "fixture-scratchpad"

    def edit(tool: str, path, extra: dict | None = None) -> str:
        payload = {"tool_name": tool, "tool_input": {"file_path": str(path)} if path else {}}
        payload.update(extra or {})
        return decision(run_hook(REVIEWER_GUARD, payload, env=env, cwd=ROOT))

    writes = [
        ("none", "Write", memory / "code-reviewer" / "probe.md", None),
        ("none", "Edit", memory / "code-reviewer" / "MEMORY.md", None),
        ("none", "Write", tmp / "probe.txt", None),
        ("none", "Write", "/private/tmp/reviewer-probe.txt", None),
        ("none", "Write", fake_scratch / "x.txt", {"scratchpad_dir": str(fake_scratch)}),
        ("deny", "Write", fake_scratch / "x.txt", None),
        ("deny", "Write", ROOT / "hooks" / "reviewer-probe.txt", None),
        ("deny", "Edit", ROOT / "README.md", None),
        ("deny", "Write", memory / "learning-doc-writer" / "x.md", None),
        ("deny", "Write", tmp / ".." / ".." / ".." / ".." / ".." / ".." / "etc" / "probe", None),
        ("deny", "Write", None, None),
    ]
    for expected, tool, path, extra in writes:
        got = edit(tool, path, extra)
        check(f"reviewer-guard {tool} {path} {extra or ''}".rstrip(), got == expected,
              f"expected {expected}, got {got}")

    for expected, commands in REVIEWER_BASH_CASES.items():
        for cmd in commands:
            payload = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            got = decision(run_hook(REVIEWER_GUARD, payload, env=env, cwd=ROOT))
            check(f"reviewer-guard {cmd!r}", got == expected, f"expected {expected}, got {got}")

    got = decision(run_hook(REVIEWER_GUARD, "not json", env=env, cwd=ROOT))
    check("reviewer-guard: an unreadable payload is denied (fails closed)", got == "deny", got)
    got = decision(run_hook(REVIEWER_GUARD, {"tool_name": "Read",
                                             "tool_input": {"file_path": "/etc/hosts"}},
                            env=env, cwd=ROOT))
    check("reviewer-guard: tools it does not police pass", got == "none", got)
    shutil.rmtree(tmp)


# ── session-rules.sh and log-instructions.sh ────────────────────────────────
# The fixture root is resolved first: macOS temp dirs live under /var, a symlink to
# /private/var, and the hook compares physical paths. HOME, the config dir and the log
# all point inside it, so the real ~/.claude/logs is never written.
def strip_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0] == "---":
        end = lines.index("---", 1)
        lines = lines[end + 1:]
    return "\n".join(lines)


def test_session_rules() -> None:
    fx = Path(tempfile.mkdtemp()).resolve()
    config, home, log = fx / "config", fx / "home", fx / "log" / "rules.jsonl"
    (config / "rules").mkdir(parents=True)
    for rule in ("java.md", "frontend.md", "shell.md"):
        shutil.copy(ROOT / "rules" / rule, config / "rules" / rule)
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(config), "HOME": str(home),
           "CLAUDE_RULES_LOG": str(log)}

    def put(rel: str, text: str = "") -> None:
        path = home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def pkg(deps: dict | None = None, dev: dict | None = None) -> str:
        return json.dumps({"dependencies": deps or {}, "devDependencies": dev or {}})

    put("javarepo/pom.xml")
    put("javarepo/src/main/java/App.java")
    subprocess.run(["git", "init", "-q", str(home / "javarepo")], check=True)
    put("gradle/settings.gradle.kts")
    put("parent/a/b/pom.xml")
    put("web/package.json", pkg({"react": "19", "next": "15"}))
    put("mono/package.json", pkg(dev={"turbo": "2"}))
    put("mono/apps/web/package.json", pkg({"react": "19"}))
    put("angular/package.json", pkg({"@angular/core": "18"}, {"react": "18"}))
    put("mobile/package.json", pkg({"react": "19", "react-native": "0.76"}))
    put("nm/package.json", pkg(dev={"eslint": "9"}))
    put("nm/node_modules/x/package.json", pkg({"react": "19"}))

    def session(rule: str, cwd: Path, run_env: dict = env):
        proc = run_hook([SESSION_RULES, rule],
                        {"cwd": str(cwd), "source": "startup", "session_id": "fixture"},
                        env=run_env)
        out = proc.stdout.strip()
        return proc.returncode, (json.loads(out) if out else None)

    cases = [
        ("java", home / "javarepo", True),
        ("java", home / "javarepo" / "src" / "main" / "java", True),
        ("java", home / "gradle", True),
        ("java", home / "parent", True),
        ("java", home / "web", False),
        ("java", home, False),
        ("java", Path("/"), False),
        ("frontend", home / "web", True),
        ("frontend", home / "mono", True),
        ("frontend", home / "mono" / "apps" / "web", True),
        ("frontend", home / "angular", False),
        ("frontend", home / "mobile", False),
        ("frontend", home / "nm", False),
        ("frontend", home / "javarepo", False),
    ]
    injected = 0
    for rule, cwd, expect in cases:
        code, out = session(rule, cwd)
        ctx = ((out or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")
        name = f"session-rules {rule} in {cwd.relative_to(fx) if fx in cwd.parents else cwd}"
        check(name, code == 0 and bool(ctx) == expect,
              f"exit {code}, expected {'inject' if expect else 'nothing'}, got {out!r:.120}")
        if expect and ctx:
            injected += 1
            head, _, body = ctx.partition("\n\n")
            check(f"{name}: marker header", head.startswith(f"[session-rules {rule} "), head[:80])
            check(f"{name}: frontmatter stripped", body.startswith("# ") and "\npaths:" not in ctx[:600],
                  body[:80])
            check(f"{name}: under the output cap", len(ctx) <= HOOK_OUTPUT_CAP, str(len(ctx)))
            check(f"{name}: no systemMessage on success", "systemMessage" not in out, str(out.keys()))

    lines = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    check("session-rules: one log line per injection", len(lines) == injected,
          f"{len(lines)} lines for {injected} injections")
    check("session-rules: log lines carry the session and marker",
          all(e.get("session_id") == "fixture" and len(e.get("marker", "")) == 8 for e in lines))

    empty = fx / "empty-config"
    empty.mkdir()
    code, out = session("java", home / "javarepo", {**env, "CLAUDE_CONFIG_DIR": str(empty)})
    check("session-rules: an unreadable rule is reported, not skipped silently",
          code == 0 and out is not None and "systemMessage" in out
          and "hookSpecificOutput" not in out, repr(out))

    big = fx / "big-config"
    (big / "rules").mkdir(parents=True)
    (big / "rules" / "java.md").write_text("# Java\n\n" + "x" * 12000 + "\n")
    code, out = session("java", home / "javarepo", {**env, "CLAUDE_CONFIG_DIR": str(big)})
    ctx = ((out or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")
    check("session-rules: an oversized rule degrades to a pointer, loudly",
          code == 0 and 0 < len(ctx) < 500 and "systemMessage" in (out or {}), repr(out)[:160])

    code, out = session("java", home / "javarepo",
                        {**env, "CLAUDE_RULES_LOG": "/nonexistent-root-dir/rules.jsonl"})
    ctx = ((out or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")
    check("session-rules: an unwritable log still injects, and says so",
          code == 0 and bool(ctx) and "cannot write" in (out or {}).get("systemMessage", ""),
          repr(out)[:160])

    proc = run_hook([SESSION_RULES, "python"], {"cwd": str(home / "web")}, env=env)
    check("session-rules: an unknown rule name exits 1", proc.returncode == 1, str(proc.returncode))

    for rule in ("java", "frontend"):
        body = strip_frontmatter((ROOT / "rules" / f"{rule}.md").read_text())
        check(f"session-rules: live rules/{rule}.md fits under the cap with its header",
              len(body) + 200 <= HOOK_OUTPUT_CAP, f"{len(body)} chars of body")

    before = len(log.read_text().splitlines()) if log.exists() else 0
    proc = run_hook(LOG_INSTRUCTIONS, {"session_id": "fixture", "cwd": "/x",
                                       "file_path": "/x/CLAUDE.md", "memory_type": "User",
                                       "load_reason": "session_start"}, env=env)
    after = log.read_text().splitlines()
    last = json.loads(after[-1]) if len(after) > before else {}
    check("log-instructions: appends the load with its reason",
          proc.returncode == 0 and last.get("load_reason") == "session_start"
          and last.get("via") == "instructions_loaded", repr(last))
    run_hook(LOG_INSTRUCTIONS, "not json", env=env)
    check("log-instructions: an unreadable payload appends nothing",
          len(log.read_text().splitlines()) == len(after))
    shutil.rmtree(fx)


# Both Sonar fixtures put this mktemp first on PATH. Sandboxed, macOS mktemp's default
# directory is unwritable and it ignores $TMPDIR, so the stub refuses, and logs, any call
# that is not an explicit template under $TMPDIR: a bare `mktemp` fails outside the sandbox
# too.
STRICT_MKTEMP = """#!/bin/bash
case "${1:-}" in
  "${TMPDIR%/}"/*X) exec /usr/bin/mktemp "$@" ;;
esac
printf '%s\\n' "$*" >>"$STUB_MKTEMP_LOG"
printf 'mktemp stub: refused %s\\n' "$*" >&2
exit 1
"""


def strict_mktemp(fx: Path, name: str) -> tuple[Callable[[], None], dict]:
    stubs, refused = fx / "mktemp-bin", fx / "mktemp-refused.log"
    stubs.mkdir()
    (stubs / "mktemp").write_text(STRICT_MKTEMP)
    (stubs / "mktemp").chmod(0o755)
    env = {"PATH": f"{stubs}:{os.environ['PATH']}", "STUB_MKTEMP_LOG": str(refused)}

    def verify() -> None:
        check(f"{name}: every temp file comes from a $TMPDIR template", not refused.exists(),
              refused.read_text().strip() if refused.exists() else "")

    return verify, env


# ── sonar-gate-on-stop.sh ───────────────────────────────────────────────────
# A stub stands in for scripts/sonar-gate.sh: each call logs its --files list, writes
# STUB_GATE_EDIT into the project mid-"scan" when set, and exits with STUB_GATE_EXIT.
# TMPDIR is a fixture directory, because the round counter and the green fingerprint live
# there. Git runs without the user's config, so a global hook or signing setting cannot
# change what the fixture commits.
STUB_GATE = """#!/bin/bash
files=""
dir=""
while [ $# -gt 0 ]; do
  case "$1" in
    --files) files=$(tr '\\n' ' ' <"$2"); shift 2 ;;
    --project-dir) dir="$2"; shift 2 ;;
    *) shift ;;
  esac
done
printf '%s\\n' "$files" >>"$STUB_GATE_LOG"
[ -z "${STUB_GATE_EDIT:-}" ] || printf 'class Late {}\\n' >"$dir/$STUB_GATE_EDIT"
exit "${STUB_GATE_EXIT:-0}"
"""


def test_sonar_gate() -> None:
    fx = Path(tempfile.mkdtemp()).resolve()
    tmp, log, gate = fx / "tmp", fx / "calls.log", fx / "gate.sh"
    tmp.mkdir()
    gate.write_text(STUB_GATE)
    gate.chmod(0o755)
    verify_mktemp, mktemp_env = strict_mktemp(fx, "sonar-gate")
    env = {**os.environ, **mktemp_env, "TMPDIR": str(tmp), "CLAUDE_SONAR_GATE": str(gate),
           "STUB_GATE_LOG": str(log), "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_NOSYSTEM": "1"}

    def git(repo: Path, *args: str) -> None:
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=fixture",
                        "-c", "user.email=fixture@example.invalid", *args],
                       check=True, capture_output=True, env=env)

    def put(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def new_repo(name: str, branch: str, commit: bool = True) -> Path:
        repo = fx / name
        put(repo / "pom.xml", "<project/>\n")
        put(repo / ".sonar-gate", "")
        put(repo / "src/main/java/App.java", "class App {}\n")
        git(fx, "init", "-q", "-b", branch, str(repo))
        if commit:
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "init")
        return repo

    def stop(repo: Path, gate_exit: int = 0, hook: str = SONAR_HOOK,
             **extra: str) -> subprocess.CompletedProcess:
        return run_hook(hook, {"cwd": str(repo), "session_id": "fixture"},
                        env={**env, "STUB_GATE_EXIT": str(gate_exit), **extra})

    def calls() -> list[list[str]]:
        return [line.split() for line in log.read_text().splitlines()] if log.exists() else []

    def rescanned(name: str, before: int, want: int = 1) -> None:
        check(f"sonar-gate: {name}", len(calls()) == before + want,
              f"{len(calls()) - before} new calls, expected {want}")

    app, new = "src/main/java/App.java", "src/main/java/New.java"
    repo = new_repo("feature", "master")
    git(repo, "checkout", "-q", "-b", "feature")
    put(repo / app, "class App { int x; }\n")
    git(repo, "commit", "-q", "-am", "feature work")
    steps = [
        ("committed work is diffed against master's fork point", None, 0, 0, 1),
        ("a Stop with nothing changed skips the scan", None, 0, 0, 1),
        ("a change outside java, poms and schemas skips the scan", ("README.md", "docs\n"),
         0, 0, 1),
        ("an edited java file re-scans", (app, "class App { int y; }\n"), 0, 0, 2),
        ("an edited pom re-scans", ("pom.xml", "<project><!-- x --></project>\n"), 0, 0, 3),
        ("a new untracked java file re-scans", (new, "class New {}\n"), 0, 0, 4),
        ("an edited untracked java file re-scans", (new, "class New { int z; }\n"), 0, 0, 5),
        ("findings block the Stop", (app, "class App { int bad; }\n"), 2, 2, 6),
        ("a red result is not remembered", None, 2, 2, 7),
        ("a green re-scan passes", None, 0, 0, 8),
        ("and a green result is remembered", None, 0, 0, 8),
    ]
    for name, change, gate_exit, want_exit, want_calls in steps:
        if change:
            put(repo / change[0], change[1])
        code = stop(repo, gate_exit).returncode
        check(f"sonar-gate: {name}", code == want_exit and len(calls()) == want_calls,
              f"exit {code}, {len(calls())} calls, expected exit {want_exit}, {want_calls} calls")
    check("sonar-gate: --files lists the committed and the untracked java files",
          calls()[3:4] == [[app, new]], repr(calls()[3:4]))
    check("sonar-gate: the fingerprint lives in TMPDIR",
          any(p.name.startswith("claude-sonar-fp-") for p in tmp.iterdir()))

    # Derived from rules/java.md, so a contract glob added there fails here until the hook
    # fingerprints it too. Java sources and poms are covered above; Gradle files are out of
    # scope, because the gate is Maven-only.
    front = (ROOT / "rules" / "java.md").read_text().split("---")[1]
    globs = [line.strip()[2:].strip("'\"") for line in front.splitlines()
             if line.strip().startswith("- ")]
    schemas = [g for g in globs if not g.endswith((".java", "pom.xml", ".gradle", ".gradle.kts"))]
    check("sonar-gate: rules/java.md yields contract globs to derive from", bool(schemas),
          repr(globs))
    for glob in schemas:
        sample = glob.replace("**/", "src/", 1).replace("**", "x").replace("*", "x")
        before = len(calls())
        put(repo / sample, "x\n")
        stop(repo)
        rescanned(f"a new {glob} re-scans", before)

    before = len(calls())
    gate.write_text(STUB_GATE + "# revised\n")
    stop(repo)
    rescanned("a changed gate script re-scans", before)

    variant = fx / "hook-variant.sh"
    variant.write_text(Path(SONAR_HOOK).read_text() + "# revised\n")
    variant.chmod(0o755)
    before = len(calls())
    stop(repo, hook=str(variant))
    rescanned("a changed hook re-scans", before)

    late = "src/main/java/Late.java"
    put(repo / app, "class App { int mid; }\n")
    stop(repo, STUB_GATE_EDIT=late)
    before = len(calls())
    stop(repo)
    rescanned("a file written mid-scan is scanned by the next Stop", before)
    check("sonar-gate: ...with that file in --files",
          any(late in c for c in calls()[before:]), repr(calls()[before:]))

    put(repo / app, "class App { int s; } // NOSONAR: fixture reason\n")
    before = len(calls())
    first, second = stop(repo), stop(repo)
    rescanned("a justified suppression scans once", before)
    check("sonar-gate: a skipped Stop still reports justified suppressions",
          "report these" in first.stderr and "report these" in second.stderr,
          repr(second.stderr[:160]))

    silent = fx / "silent-diff.sh"
    silent.write_text("#!/bin/bash\n")
    silent.chmod(0o755)
    put(repo / app, "class App { int n; } // NOSONAR\n")
    code = stop(repo, GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="color.ui",
                GIT_CONFIG_VALUE_0="always", GIT_CONFIG_KEY_1="diff.external",
                GIT_CONFIG_VALUE_1=str(silent)).returncode
    check("sonar-gate: user diff config cannot hide an unjustified suppression", code == 2,
          f"exit {code}")

    repo = new_repo("rebase", "main")
    put(repo / "src/main/java/Other.java", "class Other {}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "other")
    git(repo, "checkout", "-q", "-b", "topic")
    put(repo / app, "class App { int topic; }\n")
    git(repo, "commit", "-q", "-am", "topic work")
    stop(repo)
    git(repo, "checkout", "-q", "main")
    put(repo / "src/main/java/Other.java", "class Other { int moved; }\n")
    git(repo, "commit", "-q", "-am", "main moved")
    git(repo, "checkout", "-q", "topic")
    git(repo, "rebase", "-q", "main")
    before = len(calls())
    stop(repo)
    rescanned("a rebase onto a moved base re-scans, though the diff is identical", before)

    repo = new_repo("unpushed", "main")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    put(repo / app, "class App { int unpushed; }\n")
    git(repo, "commit", "-q", "-am", "unpushed")
    before = len(calls())
    code = stop(repo).returncode
    check("sonar-gate: an unpushed commit on main is diffed against origin/HEAD",
          code == 0 and len(calls()) == before + 1 and calls()[-1] == [app],
          f"exit {code}, calls {calls()[before:]}")

    (repo / ".sonar-gate").unlink()
    put(repo / app, "class App { int inert; }\n")
    before = len(calls())
    code = stop(repo).returncode
    check("sonar-gate: inert without .sonar-gate", code == 0 and len(calls()) == before,
          f"exit {code}, {len(calls()) - before} new calls")

    repo = new_repo("unborn", "main", commit=False)
    before = len(calls())
    codes = [stop(repo).returncode, stop(repo).returncode]
    check("sonar-gate: with no commit to fingerprint, every Stop scans",
          codes == [0, 0] and len(calls()) == before + 2,
          f"exits {codes}, {len(calls()) - before} new calls")
    verify_mktemp()
    shutil.rmtree(fx)


# ── scripts/sonar-gate.sh, whose answer the Stop hook remembers ─────────────
# Stubs on PATH stand in for curl and sleep, and a stub mvnw in the project for Maven, so
# no SonarQube is needed. TMPDIR is a fixture directory, held to by the strict mktemp. A green answer is cached, so the gate must never give one for an
# analysis it did not wait for.
STUB_MVNW = """#!/bin/bash
root=$(cd "$(dirname "$0")" && pwd)
case " $* " in
  *" clean "*) rm -rf "$root/target" ;;
  *sonar-maven-plugin*)
    if [ -n "${STUB_CE:-}" ]; then
      mkdir -p "$root/target/sonar"
      printf 'ceTaskId=%s\\n' "$STUB_CE" >"$root/target/sonar/report-task.txt"
    fi ;;
esac
exit 0
"""
STUB_CURL = r"""#!/bin/bash
page=1
for a in "$@"; do case "$a" in p=*) page=${a#p=} ;; esac; done
issues() { # $1 total, $2 count, $3 path, $4 rule
  /usr/bin/jq -n --argjson t "$1" --argjson n "$2" --arg f "$3" --arg r "$4" \
    '{paging: {total: $t}, issues: [range($n) | {component: ("local-project:" + $f),
      rule: $r, message: "fixture", line: 7}]}'
}
case "$*" in
  */api/system/status*) echo '{"status":"UP"}' ;;
  */api/ce/task*) printf '{"task":{"status":"%s"}}\n' "$STUB_CE_STATUS" ;;
  */api/issues/search*)
    case "${STUB_ISSUES:-}:$page" in
      paged:1) issues 501 500 src/Other.java java:S1 ;;
      paged:2) issues 501 1 src/main/java/App.java java:S2 ;;
      huge:*)
        if [ "$page" -le 20 ]; then issues 10001 500 src/Other.java java:S1
        else echo '{"errors":[{"msg":"Can return only the first 10000 results."}]}'; fi ;;
      error:*) echo '{"errors":[{"msg":"fixture"}]}' ;;
      html:*) echo '<html><body>502 Bad Gateway</body></html>' ;;
      listless:*) echo '{"paging":{"total":3}}' ;;
      nototal:*) issues 1 1 src/main/java/App.java java:S2 | /usr/bin/jq -c 'del(.paging)' ;;
      fraction:*) issues 501 500 src/Other.java java:S1 | /usr/bin/jq -c '.paging.total = 501.5' ;;
      *) echo '{"paging":{"total":0},"issues":[]}' ;;
    esac ;;
  *) exit 7 ;;
esac
"""


def test_sonar_gate_script() -> None:
    fx = Path(tempfile.mkdtemp()).resolve()
    stubs, project, tmp = fx / "bin", fx / "project", fx / "tmp"
    stubs.mkdir()
    project.mkdir()
    tmp.mkdir()
    verify_mktemp, mktemp_env = strict_mktemp(fx, "sonar-gate.sh")
    (project / "pom.xml").write_text("<project/>\n")
    for path, text in ((project / "mvnw", STUB_MVNW), (stubs / "curl", STUB_CURL),
                       (stubs / "sleep", "#!/bin/bash\n")):
        path.write_text(text)
        path.chmod(0o755)
    env = {**os.environ, "PATH": f"{stubs}:{mktemp_env['PATH']}", "TMPDIR": str(tmp),
           "STUB_MKTEMP_LOG": mktemp_env["STUB_MKTEMP_LOG"],
           "SONAR_TOKEN": "fixture", "SONAR_HOST_URL": "http://sonar.invalid"}
    listed = fx / "files.txt"
    listed.write_text("src/main/java/App.java\n")
    files = ("--files", str(listed))
    cases = [
        ("reports clean once the analysis succeeded", "task-1", "SUCCESS", "", (), 0, "clean"),
        ("fails without a task id to wait for", "", "SUCCESS", "", (), 1, "no ceTaskId"),
        ("fails when the analysis never finishes", "task-1", "PENDING", "", (), 1,
         "still PENDING"),
        ("fails when the server rejects the analysis", "task-1", "FAILED", "", (), 1, "FAILED"),
        ("finds a listed file's issue past the first page", "task-1", "SUCCESS", "paged", files,
         2, "App.java:7 [java:S2]"),
        ("refuses to count --files past the 10000 the API serves", "task-1", "SUCCESS", "huge",
         files, 1, "cannot be counted"),
        ("fails on an answer with no issue list", "task-1", "SUCCESS", "error", (), 1,
         "no issue list"),
        ("fails on an HTML answer, with its reason", "task-1", "SUCCESS", "html", files, 1,
         "no issue list"),
        ("fails on a total without an issue list", "task-1", "SUCCESS", "listless", files, 1,
         "no issue list"),
        ("fails on an answer with no total", "task-1", "SUCCESS", "nototal", (), 1, "or total"),
        ("fails on a total that is not a whole number", "task-1", "SUCCESS", "fraction", files,
         1, "or total"),
        ("reports the server total without --files, from one page", "task-1", "SUCCESS", "huge",
         (), 2, "10001 issue(s)"),
    ]
    for name, ce, status, issues, extra, want_exit, want in cases:
        proc = subprocess.run([SONAR_GATE, "--project-dir", str(project), "--no-boot", *extra],
                              capture_output=True, text=True, timeout=60, check=False,
                              env={**env, "STUB_CE": ce, "STUB_CE_STATUS": status,
                                   "STUB_ISSUES": issues})
        check(f"sonar-gate.sh: {name}",
              proc.returncode == want_exit and want in proc.stdout + proc.stderr,
              f"exit {proc.returncode}, output {(proc.stdout + proc.stderr).strip()[-160:]!r}")
    verify_mktemp()
    shutil.rmtree(fx)


# ── validate-readme.sh ──────────────────────────────────────────────────────
# The fixture README names a script that exists nowhere, so any invocation that really
# checks exits 2. The fixture is its own CLAUDE_CONFIG_DIR: the live README is never read.
def test_validate_readme() -> None:
    fx = Path(tempfile.mkdtemp()).resolve()
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(fx), "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_NOSYSTEM": "1"}
    table = "# fixture\n\n## What's tracked\n\n| Path | Purpose |\n|---|---|\n| `README.md` | this |\n"
    (fx / "README.md").write_text(table + "\nRun `ghost.sh`.\n")
    subprocess.run(["git", "init", "-q", str(fx)], check=True, env=env)
    subprocess.run(["git", "-C", str(fx), "add", "README.md"], check=True, env=env)

    def validate(*args: str, stdin: str = "", cwd: Path = fx) -> subprocess.CompletedProcess:
        return subprocess.run([VALIDATE_README, *args], input=stdin, capture_output=True,
                              text=True, env=env, cwd=cwd, timeout=30, check=False)

    cases = [
        ("an absolute path is checked", (str(fx / "README.md"),), fx, 2, "ghost.sh"),
        ("a relative path is checked", ("README.md",), fx, 2, "ghost.sh"),
        ("paths outside the repo say nothing was checked", ("/etc/hosts",), fx, 0,
         "nothing checked"),
        ("a relative path resolves against the working directory", ("README.md",), fx.parent, 0,
         "nothing checked"),
    ]
    for name, args, cwd, want_exit, want_err in cases:
        proc = validate(*args, cwd=cwd)
        check(f"validate-readme: {name}", proc.returncode == want_exit and want_err in proc.stderr,
              f"exit {proc.returncode}, stderr {proc.stderr.strip()[:160]!r}")
    proc = validate(stdin=json.dumps({"tool_input": {"file_path": "/etc/hosts"}}))
    check("validate-readme: the stdin form stays silent outside the repo",
          proc.returncode == 0 and not proc.stderr, repr(proc.stderr[:160]))
    (fx / "README.md").write_text(table)
    proc = validate("README.md")
    check("validate-readme: a clean README passes", proc.returncode == 0 and not proc.stderr,
          f"exit {proc.returncode}, stderr {proc.stderr.strip()[:160]!r}")
    shutil.rmtree(fx)


def run() -> None:
    test_bash_guard()
    test_reviewer_guard()
    test_session_rules()
    test_sonar_gate()
    test_sonar_gate_script()
    test_validate_readme()


if __name__ == "__main__":
    run()
    for f in _failures:
        print(f"FAIL  {f}")
    total = _passes + len(_failures)
    print(f"\n{_passes}/{total} passed")
    sys.exit(1 if _failures else 0)
