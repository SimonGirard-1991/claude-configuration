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
SESSION_RULES = os.environ.get("CLAUDE_SESSION_RULES", str(ROOT / "hooks" / "session-rules.sh"))
LOG_INSTRUCTIONS = os.environ.get("CLAUDE_LOG_INSTRUCTIONS",
                                  str(ROOT / "hooks" / "log-instructions.sh"))
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


def run() -> None:
    test_bash_guard()
    test_reviewer_guard()
    test_session_rules()


if __name__ == "__main__":
    run()
    for f in _failures:
        print(f"FAIL  {f}")
    total = _passes + len(_failures)
    print(f"\n{_passes}/{total} passed")
    sys.exit(1 if _failures else 0)
