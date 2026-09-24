#!/usr/bin/env python3
"""Fixture tests for the hook scripts in hooks/.

Each hook runs as a subprocess on a crafted payload, the way Claude Code calls it,
and the suite asserts what it prints. The tables pin behaviour in both directions:
what a hook must catch, and what it must let through untouched, because a guard
that fires on ordinary commands teaches the session to route around it.

Hook paths come from environment overrides, so a candidate can be tested before it
replaces the live file — a broken live guard gates the very session editing it:
CLAUDE_BASH_GUARD, CLAUDE_REVIEWER_GUARD, CLAUDE_SESSION_RULES.

Run: python3 scripts/test_hooks.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASH_GUARD = os.environ.get("CLAUDE_BASH_GUARD", str(ROOT / "hooks" / "bash-guard.py"))
REVIEWER_GUARD = os.environ.get("CLAUDE_REVIEWER_GUARD", str(ROOT / "hooks" / "reviewer-guard.py"))

_passes = 0
_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global _passes
    if ok:
        _passes += 1
    else:
        _failures.append(f"{name}: {detail}" if detail else name)


def run_hook(hook: str, payload, env: dict | None = None,
             cwd: Path | None = None) -> subprocess.CompletedProcess:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([hook], input=data, capture_output=True, text=True,
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


def run() -> None:
    test_bash_guard()
    test_reviewer_guard()


if __name__ == "__main__":
    run()
    for f in _failures:
        print(f"FAIL  {f}")
    total = _passes + len(_failures)
    print(f"\n{_passes}/{total} passed")
    sys.exit(1 if _failures else 0)
