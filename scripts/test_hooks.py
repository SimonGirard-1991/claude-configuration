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
CLAUDE_SONAR_GATE_HOOK, CLAUDE_SONAR_GATE, CLAUDE_SONAR_JAVA_ANNOTATIONS, CLAUDE_VALIDATE_README,
CLAUDE_VALIDATE_RULES.

Run: python3 scripts/test_hooks.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
JAVA_ANNOTATIONS = os.environ.get("CLAUDE_SONAR_JAVA_ANNOTATIONS",
                                  str(ROOT / "scripts" / "SuppressionAnnotations.java"))
VALIDATE_README = os.environ.get("CLAUDE_VALIDATE_README",
                                 str(ROOT / "hooks" / "validate-readme.sh"))
VALIDATE_RULES = os.environ.get("CLAUDE_VALIDATE_RULES",
                                str(ROOT / "hooks" / "validate-rules.sh"))
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
                          errors="surrogateescape", timeout=30, env=env, cwd=cwd, check=False)


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
        "env 2>/dev/null | grep KEY",
        "set | grep -i proxy",
        "export -p",
        'echo "$(env)"',
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
        "grep -nE 'public (void|[A-Z][A-Za-z]*) (set|get)' Foo.java",
        "grep -E 'env|printenv|set' hooks/bash-guard.py",
        "jq '[.permissions.allow | index(\"Bash(env)\")]' settings.json",
        "cat > Store.swift <<'EOF'\nfinal class Store {\n    private(set) var writes: [String] = []\n}\nEOF",
        # Known gap, pinned so a change is deliberate: a dump inside a quoted script.
        # A sandboxed command lacks the secrets named in sandbox.credentials.envVars.
        "bash -c 'cd /tmp; env; ls'",
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
def copy_rules(config: Path) -> None:
    for sub in ("rules", "conventions"):
        (config / sub).mkdir(parents=True)
        for path in (ROOT / sub).glob("*.md"):
            shutil.copy(path, config / sub / path.name)


XCODEGEN_SPEC = """name: App
targets:
  App:
    type: application
    platform: iOS
    sources: [App]
"""


def test_session_rules() -> None:
    fx = Path(tempfile.mkdtemp()).resolve()
    config, home, log = fx / "config", fx / "home", fx / "log" / "rules.jsonl"
    copy_rules(config)
    (config / "conventions" / "swift.md").write_text("# Swift conventions\n\nA fixture body.\n")
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
    put("spm/Package.swift")
    put("xcproj/App.xcodeproj/project.pbxproj")
    put("ws/sub/App.xcworkspace/contents.xcworkspacedata")
    put("xcodegen/project.yml", XCODEGEN_SPEC)
    put("xcodegen-nested/ios/project.yml", XCODEGEN_SPEC)
    put("deep2/Packages/Core/Package.swift")
    put("deep3/a/b/c/Package.swift")
    put("otheryml/project.yml", "name: docs\ntargets:\n  production:\n    type: static\n"
                                "    platform: linux\n")
    put("nested-keys/project.yml", "targets:\n  App:\n    settings:\n      type: application\n"
                                   "      platform: iOS\n")
    put("destinations/project.yml", "targets:\n  App:\n    type: application\n"
                                    "    supportedDestinations: [iOS, tvOS]\n")
    put("platform-list/project.yml", "targets:\n  App:\n    type: framework\n"
                                     "    platform: [iOS, tvOS]\n")
    put("platform-quoted/project.yml", 'targets:\n  App:\n    type: application\n'
                                       '    platform: "tvOS"\n')
    put("targets-comment/project.yml", "targets: # one per platform\n  App:\n"
                                       "    type: application\n    platform: macOS\n")
    put("type-mapping/project.yml", "targets:\n  App:\n    type:\n      kind: application\n"
                                    "    platform: iOS\n")
    put("fakeproj/Notes.xcodeproj", "a file, not a project directory\n")
    put("rn/package.json", pkg({"react": "19", "react-native": "0.80"}))
    put("rn/ios/App.xcodeproj/project.pbxproj")
    subprocess.run(["git", "init", "-q", str(home / "rn")], check=True)
    put("nmswift/node_modules/pkg/Package.swift")
    put("pods/Pods/Pods.xcodeproj/project.pbxproj")

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
        ("swift", home / "spm", True),
        ("swift", home / "xcproj", True),
        ("swift", home / "ws", True),
        ("swift", home / "xcodegen", True),
        ("swift", home / "xcodegen-nested", True),
        ("swift", home / "deep2", True),
        ("swift", home / "deep3", False),
        ("swift", home / "otheryml", False),
        ("swift", home / "nested-keys", False),
        ("swift", home / "destinations", True),
        ("swift", home / "platform-list", True),
        ("swift", home / "platform-quoted", True),
        ("swift", home / "targets-comment", True),
        ("swift", home / "type-mapping", False),
        ("swift", home / "fakeproj", False),
        ("swift", home / "rn", False),
        ("swift", home / "rn" / "ios", False),
        ("swift", home / "nmswift", False),
        ("swift", home / "pods", False),
        ("swift", home / "javarepo", False),
        ("swift", home, False),
        ("swift", Path("/"), False),
        ("java", home / "spm", False),
        ("frontend", home / "rn", False),
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
    (big / "conventions").mkdir(parents=True)
    (big / "conventions" / "java.md").write_text("# Java\n\n" + "x" * 12000 + "\n")
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

    proc = run_hook([SESSION_RULES, "cobol"], {"cwd": str(home / "web")}, env=env)
    check("session-rules: an unknown rule name exits 1", proc.returncode == 1, str(proc.returncode))

    bodies = sorted((ROOT / "conventions").glob("*.md"))
    check("session-rules: the live bodies are found", len(bodies) >= 2, str(bodies))
    settings = json.loads((ROOT / "settings.json").read_text())
    wired = [hook.get("command", "").split()[-2:] for entry in settings["hooks"]["SessionStart"]
             for hook in entry.get("hooks", [])]
    for path in bodies:
        check(f"session-rules: settings.json runs the hook for conventions/{path.name}",
              any(len(words) == 2 and words[0].endswith("hooks/session-rules.sh")
                  and words[1] == path.stem for words in wired), repr(wired))
    for path in bodies:
        body = path.read_text()
        check(f"session-rules: live conventions/{path.name} has no frontmatter",
              not body.startswith("---"), body[:40])
        check(f"session-rules: live conventions/{path.name} fits under the cap with its header",
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
  -d) case "${2:-}" in "${TMPDIR%/}"/*X) exec /usr/bin/mktemp "$@" ;; esac ;;
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
# A stub stands in for scripts/sonar-gate.sh: each call logs its --files list, and its --indexed
# list to STUB_GATE_INDEXED_LOG, writes STUB_GATE_EDIT into the project mid-"scan" when set, and
# exits with STUB_GATE_EXIT.
# TMPDIR is a fixture directory, because the round counter and the green fingerprint live
# there. Git runs without the user's config, so a global hook or signing setting cannot
# change what the fixture commits.
STUB_GATE = """#!/bin/bash
files=""
indexed=""
dir=""
while [ $# -gt 0 ]; do
  case "$1" in
    --files) files=$(tr '\\n' ' ' <"$2"); shift 2 ;;
    --indexed) indexed=$(tr '\\n' ' ' <"$2"); shift 2 ;;
    --project-dir) dir="$2"; shift 2 ;;
    *) shift ;;
  esac
done
printf '%s\\n' "$files" >>"$STUB_GATE_LOG"
printf '%s\\n' "$indexed" >>"${STUB_GATE_INDEXED_LOG:-/dev/null}"
[ -z "${STUB_GATE_EDIT:-}" ] || printf 'class Late {}\\n' >"$dir/$STUB_GATE_EDIT"
if [ -n "${STUB_GATE_SLEEP:-}" ]; then
  ( sleep "$STUB_GATE_SLEEP"; : >"$STUB_GATE_FINISHED" ) &
  wait
fi
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
           "CLAUDE_SONAR_JAVA_ANNOTATIONS": JAVA_ANNOTATIONS,
           "STUB_GATE_LOG": str(log), "STUB_GATE_INDEXED_LOG": str(fx / "indexed.log"),
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}

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

    def indexed_calls() -> list[list[str]]:
        path = fx / "indexed.log"
        return [line.split() for line in path.read_text().splitlines()] if path.exists() else []

    # A hook that exits 0 reaches the user only through a systemMessage on stdout; its stderr
    # goes to the debug log.
    def shown(proc: subprocess.CompletedProcess) -> str:
        if not proc.stdout.strip():
            return ""
        try:
            return json.loads(proc.stdout)["systemMessage"]
        except (ValueError, KeyError):
            return f"<stdout is not a systemMessage: {proc.stdout[:80]!r}>"

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
          calls()[3:4] == [["pom.xml", app, new]], repr(calls()[3:4]))
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
    check("sonar-gate: a justified suppression is shown to the user once, with file and line",
          f"{app}:1: class App" in shown(first) and shown(second) == "",
          repr((first.stdout[:160], second.stdout[:160])))
    put(repo / new, "class New { int t; } // NOSONAR: second reason\n")
    third = shown(stop(repo))
    check("sonar-gate: a suppression added to the set shows the whole set again",
          f"{app}:1:" in third and f"{new}:1:" in third, repr(third[:200]))

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
    proc = stop(repo)
    check("sonar-gate: a deleted .sonar-gate the base still has scans nothing and tells the user",
          proc.returncode == 0 and len(calls()) == before and "OFF" in shown(proc),
          f"exit {proc.returncode}, {len(calls()) - before} new calls, stdout {proc.stdout!r}")

    repo = new_repo("never-gated", "main")
    git(repo, "rm", "-q", ".sonar-gate")
    git(repo, "commit", "-q", "-m", "no gate")
    put(repo / app, "class App { int quiet; }\n")
    before = len(calls())
    proc = stop(repo)
    check("sonar-gate: silent and inert where the base has no .sonar-gate",
          proc.returncode == 0 and len(calls()) == before and proc.stdout == "",
          f"exit {proc.returncode}, {len(calls()) - before} new calls, stdout {proc.stdout!r}")

    # A Sonar property that excludes, skips or narrows analysis hides findings the way NOSONAR
    # does. No java file changes in the table, so nothing is scanned: the audit runs anyway.
    repo = new_repo("pom-audit", "main")

    def pom(body: str) -> str:
        return f"<project>\n  <properties>\n{body}  </properties>\n</project>\n"

    def reset(repo: Path) -> None:
        git(repo, "checkout", "-q", "--", ".")
        git(repo, "clean", "-fdq")

    multicriteria = (
        "    <!-- Module declarations sit alone in their package. -->\n"
        "    <sonar.issue.ignore.multicriteria>e1</sonar.issue.ignore.multicriteria>\n"
        "    <sonar.issue.ignore.multicriteria.e1.ruleKey>java:S4032"
        "</sonar.issue.ignore.multicriteria.e1.ruleKey>\n"
        "    <sonar.issue.ignore.multicriteria.e1.resourceKey>**/package-info.java"
        "</sonar.issue.ignore.multicriteria.e1.resourceKey>\n")
    pom_cases = [
        ("an uncommented pom exclusion blocks", "pom.xml",
         pom("    <sonar.exclusions>**/App.java</sonar.exclusions>\n"), 2, ["pom.xml:3:"]),
        ("a same-line comment justifies a pom exclusion, and the report shows it", "pom.xml",
         pom("    <sonar.exclusions>**/gen/**</sonar.exclusions> <!-- generated -->\n"), 0,
         ["pom.xml:3: <sonar.exclusions>**/gen/**</sonar.exclusions> (reason: generated)"]),
        ("a comment just above a block justifies every property of it", "pom.xml",
         pom(multicriteria), 0,
         ["pom.xml:4: ", "pom.xml:5: ", "pom.xml:6: ",
          "(reason: Module declarations sit alone in their package.)"]),
        ("a multi-line value is one property, justified by the comment above it", "pom.xml",
         pom("    <!-- generated code -->\n    <sonar.exclusions>\n      **/gen/**\n"
             "    </sonar.exclusions>\n"), 0,
         ["pom.xml:4: <sonar.exclusions>**/gen/**</sonar.exclusions> (reason: generated code)"]),
        ("a property that borrows its block's reason shows that reason", "pom.xml",
         pom("    <!-- Generated code. -->\n"
             "    <sonar.exclusions>**/gen/**</sonar.exclusions>\n"
             "    <sonar.coverage.exclusions>**/App.java</sonar.coverage.exclusions>\n"), 0,
         ["pom.xml:5: <sonar.coverage.exclusions>**/App.java</sonar.coverage.exclusions>"
          " (reason: Generated code.)"]),
        ("a comment above a blank line justifies nothing", "pom.xml",
         pom("    <!-- reason -->\n\n    <sonar.skip>true</sonar.skip>\n"), 2, ["pom.xml:5:"]),
        ("an empty comment justifies nothing", "pom.xml",
         pom("    <!-- -->\n    <sonar.exclusions>**/App.java</sonar.exclusions>\n"), 2,
         ["pom.xml:4:"]),
        ("a property inside a comment is not a property", "pom.xml",
         pom("    <!-- <sonar.exclusions>**/*</sonar.exclusions> -->\n"), 0, []),
        ("a tag named in a comment cannot swallow a real property", "pom.xml",
         pom("    <!-- see <sonar.exclusions> -->\n\n"
             "    <sonar.exclusions>**/App.java</sonar.exclusions>\n"), 2, ["pom.xml:5:"]),
        ("file.suffixes narrows analysis, so it needs a reason", "pom.xml",
         pom("    <sonar.java.file.suffixes>.nope</sonar.java.file.suffixes>\n"), 2,
         ["pom.xml:3:"]),
        ("a Sonar property in .mvn/maven.config blocks: only a pom is accepted",
         ".mvn/maven.config", "-Dsonar.coverage.exclusions=**/*\n", 2,
         [".mvn/maven.config:1:"]),
        ("any Sonar property needs a reason, not only the ones that look narrowing", "pom.xml",
         pom("    <sonar.lang.patterns.java>**/*.none</sonar.lang.patterns.java>\n"), 2,
         ["pom.xml:3: <sonar.lang.patterns.java>"]),
        ("a property that is not Sonar's passes silently", "pom.xml",
         pom("    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>\n"), 0, []),
        ("a generated pom copy is not audited", "dependency-reduced-pom.xml",
         pom("    <sonar.exclusions>**/App.java</sonar.exclusions>\n"), 0, []),
        ("a module pom is audited", "backend/pom.xml",
         pom("    <sonar.exclusions>**/App.java</sonar.exclusions>\n"), 2,
         ["backend/pom.xml:3:"]),
        # Tag forms Maven reads as the same property.
        ("a space before > is still the property", "pom.xml",
         pom("    <sonar.coverage.exclusions >**/App.java</sonar.coverage.exclusions>\n"), 2,
         ["pom.xml:3: <sonar.coverage.exclusions>**/App.java</sonar.coverage.exclusions>"]),
        ("a newline before > is still the property", "pom.xml",
         pom("    <sonar.exclusions\n      >**/Gen.java</sonar.exclusions>\n"), 2,
         ["pom.xml:3: <sonar.exclusions>**/Gen.java</sonar.exclusions>"]),
        ("an attribute on the start tag is still the property", "pom.xml",
         pom('    <sonar.cpd.exclusions a="b">**/App.java</sonar.cpd.exclusions>\n'), 2,
         ["pom.xml:3: <sonar.cpd.exclusions>**/App.java</sonar.cpd.exclusions>"]),
        ("an end tag with whitespace swallows nothing after it", "pom.xml",
         pom("    <sonar.exclusions>**/gen/**</sonar.exclusions > <!-- generated -->\n"
             "    <a>" + "x" * 250 + "</a>\n"
             "    <sonar.coverage.exclusions>**/App.java</sonar.coverage.exclusions>\n"), 2,
         ["pom.xml:5: <sonar.coverage.exclusions>**/App.java</sonar.coverage.exclusions>"]),
        ("a self-closing tag swallows nothing after it", "pom.xml",
         pom("    <sonar.projectName />\n\n"
             "    <sonar.exclusions>**/App.java</sonar.exclusions>\n"), 2, ["pom.xml:5:"]),
        ("a long value is shown whole", "pom.xml",
         pom("    <!-- generated -->\n    <sonar.exclusions>" + "**/gen/**," * 30
             + "**/App.java</sonar.exclusions>\n"), 0, ["**/App.java</sonar.exclusions>"]),
    ]
    for name, path, text, want_exit, want_shown in pom_cases:
        reset(repo)
        put(repo / path, text)
        before = len(calls())
        proc = stop(repo)
        where = proc.stderr if want_exit == 2 else shown(proc)
        # A pom is a source the Maven scan reads, so a passing change to one is scanned; a
        # refusal comes before any scan.
        scans = 1 if want_exit == 0 and path.split("/")[-1] == "pom.xml" else 0
        ok = (proc.returncode == want_exit and len(calls()) == before + scans
              and all(w in where for w in want_shown)
              and (bool(want_shown) or proc.stdout == ""))
        check(f"sonar-gate: {name}", ok,
              f"exit {proc.returncode}, {len(calls()) - before} calls, "
              f"stdout {proc.stdout[:200]!r}, stderr {proc.stderr[:200]!r}")

    reset(repo)
    put(repo / app, "class App { int red; }\n")
    put(repo / "pom.xml", pom("    <sonar.exclusions>**/App.java</sonar.exclusions>\n"))
    before = len(calls())
    proc = stop(repo, GIT_CONFIG_COUNT="3", GIT_CONFIG_KEY_0="diff.noprefix",
                GIT_CONFIG_VALUE_0="true", GIT_CONFIG_KEY_1="color.ui",
                GIT_CONFIG_VALUE_1="always", GIT_CONFIG_KEY_2="diff.external",
                GIT_CONFIG_VALUE_2=str(silent))
    check("sonar-gate: excluding a changed file in the pom blocks before any scan, "
          "whatever the user's diff config",
          proc.returncode == 2 and len(calls()) == before and "pom.xml:3:" in proc.stderr,
          f"exit {proc.returncode}, {len(calls()) - before} calls, stderr {proc.stderr[:200]!r}")

    # What fooled a diff-parsing audit: merged hunks numbered an uncommented exclusion onto an
    # unrelated comment, and a -diff attribute hid the added lines outright.
    reset(repo)
    put(repo / "pom.xml", pom("    <a>1</a>\n    <b>2</b>\n"))
    git(repo, "commit", "-q", "-am", "two properties")
    put(repo / "pom.xml", pom("    <!-- first insertion -->\n    <a>1</a>\n    <b>2</b>\n"
                              "    <sonar.exclusions>**/App.java</sonar.exclusions>\n"))
    put(repo / ".gitattributes", "pom.xml -diff\n*.java -diff\n")
    put(repo / app, "class App { int red; } // NOSONAR\n")
    before = len(calls())
    proc = stop(repo, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="diff.interHunkContext",
                GIT_CONFIG_VALUE_0="5")
    check("sonar-gate: .gitattributes and merged hunks hide no suppression and misnumber none",
          proc.returncode == 2 and len(calls()) == before
          and "pom.xml:6: <sonar.exclusions>" in proc.stderr and f"{app}:1:" in proc.stderr,
          f"exit {proc.returncode}, {len(calls()) - before} calls, stderr {proc.stderr[:300]!r}")

    reset(repo)
    legacy = "    <sonar.exclusions>\n      **/gen/**\n    </sonar.exclusions>\n"
    put(repo / "pom.xml", pom(legacy))
    git(repo, "commit", "-q", "-am", "legacy exclusion")
    proc = stop(repo)
    check("sonar-gate: a suppression the base already has is not audited again",
          proc.returncode == 0 and proc.stdout == "",
          f"exit {proc.returncode}, stderr {proc.stderr[:200]!r}")
    put(repo / "pom.xml", pom(legacy.replace("**/gen/**\n", "**/gen/**\n      **/App.java\n")))
    proc = stop(repo)
    check("sonar-gate: a value added inside an existing multi-line property blocks",
          proc.returncode == 2
          and "pom.xml:3: <sonar.exclusions>**/gen/** **/App.java</sonar.exclusions>"
          in proc.stderr,
          f"exit {proc.returncode}, stderr {proc.stderr[:300]!r}")

    # The java audit compares blobs too: paths arrive unquoted, lines are counted rather
    # than treated as a set, and a moved file is audited as new.
    reset(repo)
    sud, legacy_java = "src/main/java/Süd.java", "src/main/java/Legacy.java"
    grandfathered = "class Legacy {\n    void f() {\n        g(); // NOSONAR\n    }\n}\n"
    put(repo / sud, "class Sud {}\n")
    put(repo / legacy_java, grandfathered)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "a grandfathered bare NOSONAR")
    java_cases = [
        ("a bare NOSONAR in a non-ASCII path blocks",
         lambda: put(repo / sud, "class Sud {} // NOSONAR\n"), f"{sud}:1:"),
        ("a second copy of a grandfathered bare NOSONAR blocks",
         lambda: put(repo / legacy_java, grandfathered.replace(
             "        g(); // NOSONAR\n", "        g(); // NOSONAR\n" * 2)),
         f"{legacy_java}:4:"),
        ("a file moved since the base is audited as new",
         lambda: (repo / legacy_java).rename(repo / "src/main/java/Moved.java"),
         "src/main/java/Moved.java:3:"),
    ]
    for name, change, want in java_cases:
        reset(repo)
        change()
        before = len(calls())
        proc = stop(repo)
        check(f"sonar-gate: {name}",
              proc.returncode == 2 and len(calls()) == before and want in proc.stderr,
              f"exit {proc.returncode}, {len(calls()) - before} calls, "
              f"stderr {proc.stderr[:300]!r}")

    # Latin-1 sources under a UTF-8 locale, pinned here rather than inherited: macOS awk
    # aborts on such a byte and grep stops matching the line, unless the hook runs them
    # under LC_ALL=C.
    utf8 = {"LC_ALL": "en_US.UTF-8", "LANG": "en_US.UTF-8"}
    latin1_cases = [
        ("a bare NOSONAR on a Latin-1 line blocks", "src/main/java/Cafe.java",
         'class Cafe { String s = "café"; } // NOSONAR\n', 2, "src/main/java/Cafe.java:1:"),
        ("a bare NOSONAR in a Latin-1 file blocks", "src/main/java/Vieux.java",
         "// écrit en Latin-1\nclass Vieux {} // NOSONAR\n", 2, "src/main/java/Vieux.java:2:"),
        ("an uncommented exclusion in a Latin-1 pom blocks", "pom.xml",
         '<?xml version="1.0" encoding="ISO-8859-1"?>\n'
         + pom("    <name>Société</name>\n"
               "    <sonar.exclusions>**/App.java</sonar.exclusions>\n"), 2, "pom.xml:5:"),
    ]
    for name, path, text, want_exit, want in latin1_cases:
        reset(repo)
        (repo / path).write_bytes(text.encode("latin-1"))
        before = len(calls())
        proc = stop(repo, **utf8)
        check(f"sonar-gate: {name}",
              proc.returncode == want_exit and len(calls()) == before
              and want.encode() in proc.stderr.encode("utf-8", "surrogateescape"),
              f"exit {proc.returncode}, {len(calls()) - before} calls, "
              f"stderr {proc.stderr[:300]!r}")

    # Code Sonar never analyzes cannot hide a finding, so a suppression there is not audited.
    # The root pom's sonar.exclusions draws that line the way Sonar reads it: "**/" spans any
    # directories, none included, and "*" stops at a "/".
    repo = new_repo("generated", "main")
    put(repo / "pom.xml", pom("    <!-- Generated code. -->\n"
                              "    <sonar.exclusions>**/gen/**, **/flat/*.java</sonar.exclusions>\n"))
    put(repo / "backend/pom.xml", pom("    <!-- Module-level. -->\n"
                                      "    <sonar.exclusions>**/modgen/**</sonar.exclusions>\n"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "exclusions")
    generated = ('/*\n * This file is generated by a fixture.\n */\n'
                 '@SuppressWarnings({ "all", "unchecked" })\nclass G {}\n')
    exempt_cases = [
        ("a suppression in code the root pom excludes is not audited",
         "backend/src/main/gen/app/G.java", 0),
        ("a suppression at the top of an excluded tree is not audited", "gen/G.java", 0),
        ("a file matching a single * is not audited", "src/flat/G.java", 0),
        ("a single * in an exclusion stops at a /", "src/flat/deep/G.java", 2),
        ("an exclusion in a module pom exempts nothing", "backend/src/modgen/G.java", 2),
        ("a suppression outside the excluded code is still audited", "src/main/java/G.java", 2),
    ]
    for name, path, want_exit in exempt_cases:
        reset(repo)
        put(repo / path, generated)
        proc = stop(repo)
        check(f"sonar-gate: {name}",
              proc.returncode == want_exit and (want_exit == 0 or f"{path}:4:" in proc.stderr),
              f"exit {proc.returncode}, stderr {proc.stderr[:300]!r}")

    reset(repo)
    put(repo / "gen/H.java", "class H {}\n")
    proc = stop(repo)
    check("sonar-gate: hand-written Java in code the root pom excludes blocks: excluded code is "
          "generated, and carries its generator's header",
          proc.returncode == 2 and "gen/H.java: kept out of analysis by the root pom's "
          "sonar.exclusions, with no generator's header" in proc.stderr,
          f"exit {proc.returncode}, stderr {proc.stderr[:300]!r}")

    reset(repo)
    put(repo / "pom.xml", pom("    <!-- Generated code. -->\n"
                              "    <sonar.exclusions>**/gen/**, **/late/**</sonar.exclusions>\n"))
    put(repo / "late/G.java", generated)
    proc = stop(repo)
    check("sonar-gate: an exclusion added in the same change exempts nothing yet",
          proc.returncode == 2 and "late/G.java:4:" in proc.stderr,
          f"exit {proc.returncode}, stderr {proc.stderr[:300]!r}")

    # A TypeScript project named in .sonar-gate: its sources join the file set, its NOSONAR lines
    # the audit, and its sonar-project.properties is held to the pom rule.
    repo = new_repo("web", "main")
    props = "web/sonar-project.properties"
    committed_props = "# Generated API types.\nsonar.exclusions=src/gen/**\n"
    put(repo / ".sonar-gate", "js-project = web\n")
    put(repo / props, committed_props)
    ts = "web/src/a.ts"
    put(repo / ts, "export const a = 1;\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "web")
    put(repo / ts, "export const a = 2;\n")
    before = len(calls())
    proc = stop(repo)
    check("sonar-gate: an edited TypeScript file re-scans, listed in --files",
          proc.returncode == 0 and calls()[before:] == [[ts]],
          f"exit {proc.returncode}, calls {calls()[before:]}")
    put(repo / ts, "export const a = 3; // NOSONAR\n")
    proc = stop(repo)
    check("sonar-gate: a bare NOSONAR in TypeScript blocks",
          proc.returncode == 2 and f"{ts}:1:" in proc.stderr,
          f"exit {proc.returncode}, stderr {proc.stderr[:200]!r}")
    put(repo / ts, "export const a = 3; // NOSONAR: fixture reason\n")
    proc = stop(repo)
    check("sonar-gate: a TypeScript NOSONAR with its reason passes and is reported",
          proc.returncode == 0 and f"{ts}:1:" in shown(proc),
          f"exit {proc.returncode}, stdout {proc.stdout[:200]!r}")
    props_cases = [
        ("an uncommented exclusion in sonar-project.properties blocks",
         committed_props + "\nsonar.coverage.exclusions=**/*\n", 2,
         f"{props}:4: sonar.coverage.exclusions=**/*"),
        ("# lines just above justify a properties exclusion, and the report shows them whole",
         committed_props + "# Coverage is not\n# measured.\nsonar.coverage.exclusions=**/*\n", 0,
         "(reason: Coverage is not measured.)"),
        ("a property just below a justified one borrows its reason, visibly",
         committed_props + "sonar.cpd.exclusions=**/*\n", 0,
         f"{props}:3: sonar.cpd.exclusions=**/* (reason: Generated API types.)"),
        ("a value continued over two lines is one property",
         committed_props + "\nsonar.test.inclusions=a,\\\n  b\n", 2,
         f"{props}:4: sonar.test.inclusions=a,b"),
        ("a file-size cap in sonar-project.properties narrows analysis, so it blocks",
         committed_props + "\nsonar.javascript.maxFileSize=1\n", 2,
         f"{props}:4: sonar.javascript.maxFileSize=1"),
        ("an escaped key blocks, whatever it decodes to",
         committed_props + "# Fixture reason.\nsonar\\u002eexclusions=**/*\n", 2,
         "an escaped key"),
        ("a comment ending in a backslash continues nothing: the exclusion under it is audited",
         committed_props + "\n# fixture \\\nsonar.coverage.exclusions=**/*\n", 0,
         f"{props}:5: sonar.coverage.exclusions=**/* (reason: fixture"),
        ("any Sonar key in sonar-project.properties needs a reason",
         committed_props + "\nsonar.lang.patterns.ts=**/*.none\n", 2,
         f"{props}:4: sonar.lang.patterns.ts=**/*.none"),
    ]
    for name, text, want_exit, want in props_cases:
        reset(repo)
        put(repo / props, text)
        proc = stop(repo)
        where = proc.stderr if want_exit == 2 else shown(proc)
        check(f"sonar-gate: {name}",
              proc.returncode == want_exit and want in where and (want or proc.stdout == ""),
              f"exit {proc.returncode}, stdout {proc.stdout[:200]!r}, stderr {proc.stderr[:200]!r}")

    # scope = project: a commit alone moves the fingerprint, and the gate counts the whole project.
    repo = new_repo("whole", "main")
    put(repo / ".sonar-gate", "scope = project\n")
    git(repo, "commit", "-q", "-am", "whole project")
    before = len(calls())
    first, second = stop(repo), stop(repo)
    check("sonar-gate: scope = project scans after a commit, with no --files, once",
          first.returncode == 0 and second.returncode == 0 and calls()[before:] == [[]],
          f"exits {first.returncode}/{second.returncode}, calls {calls()[before:]}")
    put(repo / ".sonar-gate", "scope = everything\n")
    before = len(calls())
    proc = stop(repo)
    check("sonar-gate: an unknown scope turns the gate OFF, loudly",
          proc.returncode == 0 and len(calls()) == before and "OFF" in shown(proc),
          f"exit {proc.returncode}, stdout {proc.stdout[:200]!r}")

    # Failures reach the user whole, through a systemMessage: a Stop hook's exit 1 would show
    # only the first line of its stderr.
    repo = new_repo("failing", "main")
    put(repo / app, "class App { int down; }\n")
    proc = stop(repo, 1)
    check("sonar-gate: a gate that cannot run says so to the user and does not block",
          proc.returncode == 0 and "could not run" in shown(proc) and "OFF" in shown(proc),
          f"exit {proc.returncode}, stdout {proc.stdout[:200]!r}")
    codes = [stop(repo, 2) for _ in range(3)]
    last = stop(repo, 2)
    check("sonar-gate: after three red rounds the gate stops blocking and tells the user",
          [p.returncode for p in codes] == [2, 2, 0] and "still red" in shown(codes[2])
          and last.returncode == 2,
          f"exits {[p.returncode for p in codes]} then {last.returncode}, "
          f"third stdout {codes[2].stdout[:200]!r}")

    # The JS project counts whole: its analyzer reads .mts and more, and a README that names
    # NOSONAR in prose is no suppression.
    repo = new_repo("web-whole", "main")
    put(repo / ".sonar-gate", "js-project = web\n")
    put(repo / "web/sonar-project.properties", "sonar.projectName=x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "web")
    put(repo / "web/vitest.config.mts", "export default {};\n")
    put(repo / "web/README.md", "Never add a bare NOSONAR.\n")
    before = len(calls())
    proc = stop(repo)
    check("sonar-gate: an .mts file is listed, and prose naming NOSONAR is not audited",
          proc.returncode == 0 and calls()[before:] == [["web/README.md", "web/vitest.config.mts"]],
          f"exit {proc.returncode}, calls {calls()[before:]}, stderr {proc.stderr[:200]!r}")

    # Every form the analyzers take as a suppression, as measured on the server: SonarJS takes a
    # comment starting with NOSONAR in any case, ESLint directives and inline ESLint config; the
    # CSS analyzer stylelint directives; sonar-java @SuppressWarnings by type.
    repo = new_repo("vocabulary", "main")
    put(repo / ".sonar-gate", "js-project = web\n")
    put(repo / "web/sonar-project.properties", "sonar.projectName=x\n")
    put(repo / "web/src/a.ts", "export const a = 1;\n")
    put(repo / "web/src/a.css", ".a { color: red; }\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "vocabulary")
    java_line = "class App { int v; }"
    vocabulary = [
        ("a lower-case nosonar blocks", "web/src/a.ts", "export const b = 1; // nosonar\n", 2),
        ("a block-comment NoSonar blocks", "web/src/a.ts", "export const b = 1; /* NoSonar */\n", 2),
        ("a nosonar with its reason passes", "web/src/a.ts",
         "export const b = 1; // nosonar: fixture reason\n", 0),
        ("an eslint-disable-next-line blocks", "web/src/a.ts",
         "// eslint-disable-next-line\nexport const b = 1;\n", 2),
        ("an eslint-disable-line naming a rule blocks without a description", "web/src/a.ts",
         "export const b = 1; // eslint-disable-line no-eval\n", 2),
        ("an ESLint directive with its -- description passes", "web/src/a.ts",
         "// eslint-disable-next-line no-eval -- fixture reason\nexport const b = 1;\n", 0),
        ("a decrement is no ESLint description", "web/src/a.ts",
         "let c = 2; c--; // eslint-disable-line\n", 2),
        ("a file-wide eslint-disable blocks", "web/src/a.ts", "/* eslint-disable */\nexport const b = 1;\n", 2),
        ("an inline ESLint rule config blocks", "web/src/a.ts",
         "/* eslint no-eval: off */\nexport const b = 1;\n", 2),
        ("a stylelint directive blocks", "web/src/a.css",
         "/* stylelint-disable-next-line */\n.b {}\n", 2),
        ("a CSS NOSONAR blocks", "web/src/a.css", ".b {} /* NOSONAR */\n", 2),
        ("prose naming eslint is no suppression", "web/src/a.ts",
         "// eslint cannot see this one.\nexport const b = 1;\n", 0),
        ("a noſonar blocks: JavaScript upper-cases ſ to S", "web/src/a.ts",
         "export const b = 1; // noſonar\n", 2),
        ("a noſonar with its reason passes", "web/src/a.ts",
         "export const b = 1; // noſonar: fixture reason\n", 0),
        ("an ESLint config wrapped onto the comment's next line blocks", "web/src/a.ts",
         "/*\n  eslint no-eval: off\n*/\nexport const b = 1;\n", 2),
        ("an eslint alone at the end of a comment's first line blocks", "web/src/a.ts",
         "/* eslint\n  no-eval: off */\nexport const b = 1;\n", 2),
        ("an ESLint config after a no-break space blocks", "web/src/a.ts",
         "/*\u00a0eslint no-eval: off */\nexport const b = 1;\n", 2),
        ("a wrapped ESLint config with its -- description passes", "web/src/a.ts",
         "/*\n  eslint no-eval: off -- fixture reason\n*/\nexport const b = 1;\n", 0),
        ("a global directive blocks", "web/src/a.ts", "/* global fixture */\nexport const b = 1;\n", 2),
        ("eslint after a JSDoc star is no directive", "web/src/a.ts",
         "/**\n * eslint no-eval: off\n */\nexport const b = 1;\n", 0),
        ("a NOSONAR after a lone carriage return blocks", "web/src/a.ts",
         "export const b = 1; // NOSONAR: fixture reason\r// NOSONAR\n", 2),
        ("a NOSONAR after a line separator blocks", "web/src/a.ts",
         "export const b = 1; // NOSONAR: fixture reason\u2028// NOSONAR\n", 2),
        ("a spaced @ SuppressWarnings blocks", "src/main/java/App.java",
         '@ SuppressWarnings("java:S1")\n' + java_line + "\n", 2),
        ("a qualified @java.lang.SuppressWarnings blocks", "src/main/java/App.java",
         '@java.lang.SuppressWarnings("java:S1")\n' + java_line + "\n", 2),
        ("a qualified @java.lang.SuppressWarnings with its reason passes", "src/main/java/App.java",
         '@java.lang.SuppressWarnings("java:S1") // fixture reason\n' + java_line + "\n", 0),
        ("\"all\" in braces blocks, reason or not", "src/main/java/App.java",
         '@SuppressWarnings({ "all" }) // fixture reason\n' + java_line + "\n", 2),
        ("a constant for @SuppressWarnings blocks, reason or not", "src/main/java/App.java",
         'class App {\n  static final String S = "java:S1";\n'
         '  @SuppressWarnings(S) // fixture reason\n  int v;\n}\n', 2),
        ("a concatenation for @SuppressWarnings blocks, reason or not", "src/main/java/App.java",
         '@SuppressWarnings("a" + "ll") // fixture reason\n' + java_line + "\n", 2),
        ("@SuppressWarnings with its value on the next line blocks", "src/main/java/App.java",
         '@SuppressWarnings( // fixture reason\n    "all")\n' + java_line + "\n", 2),
        ("an @ alone on the line before SuppressWarnings blocks", "src/main/java/App.java",
         '@\nSuppressWarnings("java:S1") // fixture reason\n' + java_line + "\n", 2),
        ("string literals in braces after value = pass with a reason", "src/main/java/App.java",
         '@SuppressWarnings(value = { "java:S1", "java:S2" }) // fixture reason\n'
         + java_line + "\n", 0),
        ("naming SuppressWarnings.class is no suppression", "src/main/java/App.java",
         "class App { String n = SuppressWarnings.class.getSimpleName(); }\n", 0),
        ("@Generated blocks, reason or not", "src/main/java/App.java",
         '@Generated("fixture") // fixture reason\n' + java_line + "\n", 2),
        ("a qualified @javax.annotation.processing.Generated blocks", "src/main/java/App.java",
         '@javax.annotation.processing.Generated("fixture")\n' + java_line + "\n", 2),
        ("an import of Generated is no annotation", "src/main/java/App.java",
         "import jakarta.annotation.Generated;\n" + java_line + "\n", 0),
        ("a comment naming @Generated is no annotation", "src/main/java/App.java",
         "// jOOQ writes no @Generated: sonar-java would skip the class\n" + java_line + "\n", 0),
        ("Generated.class is no annotation", "src/main/java/App.java",
         "class App { Class<?> g = javax.annotation.processing.Generated.class; }\n", 0),
        ("a pom comment line starting with exported is no ESLint directive", "pom.xml",
         "<project>\n  <!-- Sources\n       exported by tools/jooq-codegen. -->\n</project>\n", 0),
        ("a \\u escape for a vertical tab passes", "src/main/java/App.java",
         'class App { String vt = "a\\u000Bb"; }\n', 0),
        ("@Generated spread over two lines blocks", "src/main/java/App.java",
         '@\nGenerated("fixture")\n' + java_line + "\n", 2),
        ("@Generated after a comment blocks", "src/main/java/App.java",
         '@/* fixture */Generated("fixture")\n' + java_line + "\n", 2),
        ("a comment saying Generated is no annotation", "src/main/java/App.java",
         "// Generated ids come from the database.\n" + java_line + "\n", 0),
        ("a \\u escape for an ASCII letter blocks", "src/main/java/App.java",
         '@\\u0053uppressWarnings("java:S1") // fixture reason\n' + java_line + "\n", 2),
        ("a \\u escape for NUL passes", "src/main/java/App.java",
         'class App { String s = "\\u0000"; }\n', 0),
        ("an escaped backslash before u is no escape", "src/main/java/App.java",
         'class App { String s = "\\\\u0041"; }\n', 0),
        # What javac reads and a text match does not (review of 2026-10-12).
        ("@SuppressWarnings after a // in a string blocks", "src/main/java/App.java",
         'class App { String u = "http://x"; @SuppressWarnings("all") int d; }\n', 2),
        ("@SuppressWarnings after a // in a block comment blocks", "src/main/java/App.java",
         'class App { /* see http://x */ @SuppressWarnings("all") int d; }\n', 2),
        ("comments around SuppressWarnings block", "src/main/java/App.java",
         'class App { @/**/SuppressWarnings/**/("java:S1") // fixture reason\n int d; }\n', 2),
        ("@, SuppressWarnings and its values on three lines block", "src/main/java/App.java",
         'class App {\n  @\n  SuppressWarnings\n  ("all")\n  int d;\n}\n', 2),
        ("a qualified name broken before .SuppressWarnings blocks", "src/main/java/App.java",
         'class App {\n  @java.lang\n  .SuppressWarnings\n  ("all")\n  int d;\n}\n', 2),
        ("a zero-width space inside SuppressWarnings blocks", "src/main/java/App.java",
         'class App { @Suppress\u200bWarnings("all") int d; }\n', 2),
        ("an escaped NUL inside SuppressWarnings blocks", "src/main/java/App.java",
         'class App { @Suppress\\u0000Warnings("all") int d; }\n', 2),
        ("a soft hyphen inside a qualified Generated blocks", "src/main/java/App.java",
         'class App { @javax.annotation.processing.Gen\u00aderated("x") void m() {} }\n', 2),
        ("a raw NUL earlier on the line hides no @SuppressWarnings", "src/main/java/App.java",
         'class App { String s = "\0"; @SuppressWarnings("all") int d; }\n', 2),
        ("a raw NUL earlier on the line hides no NOSONAR", "web/src/a.ts",
         'export const s = "\0"; // NOSONAR\n', 2),
        ("an eslint-enable suppresses nothing, so it needs no reason", "web/src/a.ts",
         "/* eslint-enable no-eval */\nexport const b = 1;\n", 0),
    ]
    for name, path, text, want_exit in vocabulary:
        reset(repo)
        put(repo / path, text)
        proc = stop(repo)
        check(f"sonar-gate: {name}",
              proc.returncode == want_exit and (want_exit == 0 or f"{path}:" in proc.stderr),
              f"exit {proc.returncode}, stderr {proc.stderr[:300]!r}")
    reset(repo)
    put(repo / app, 'class App { @Suppress\u200bWarnings("all") int d; }\n')
    proc = stop(repo)
    check("sonar-gate: what javac reads and the line audit cannot is shown with its hidden "
          "character escaped",
          proc.returncode == 2 and '@Suppress\\u200bWarnings("all") (javac reads this' in proc.stderr,
          f"exit {proc.returncode}, stderr {proc.stderr[:300]!r}")
    reset(repo)
    put(repo / app, java_line + "\n")
    proc = stop(repo, CLAUDE_SONAR_JAVA_ANNOTATIONS=str(fx / "missing.java"))
    check("sonar-gate: javac's reader failing turns the checks OFF, loudly",
          proc.returncode == 0 and "audit failed" in shown(proc) and "OFF" in shown(proc),
          f"exit {proc.returncode}, stdout {proc.stdout[:200]!r}")
    reset(repo)
    put(repo / app, '@Generated("fixture") // fixture reason\n' + java_line + "\n")
    proc = stop(repo)
    check("sonar-gate: @Generated is refused as never accepted, not as a suppression without reason",
          proc.returncode == 2 and "which the gate never accepts:\n  src/main/java/App.java:1:"
          in proc.stderr and "unjustified" not in proc.stderr,
          f"exit {proc.returncode}, stderr {proc.stderr[:300]!r}")

    # The hand-rolled readers against what Maven and properties-file read.
    reset(repo)
    put(repo / "pom.xml", pom("    <description><![CDATA[<!--]]></description>\n"
                              "    <sonar.exclusions>src/**</sonar.exclusions>\n"
                              "    <!-- -->\n"))
    proc = stop(repo)
    check("sonar-gate: a pom whose Sonar properties the audit reads apart from xmllint blocks",
          proc.returncode == 2 and "xmllint: sonar.exclusions=src/**" in proc.stderr
          and "audit:" not in proc.stderr,
          f"exit {proc.returncode}, stderr {proc.stderr[:300]!r}")
    reset(repo)
    put(repo / "pom.xml", pom("    <!-- Generated code. -->\n"
                              "    <sonar.exclusions>gen/**<![CDATA[,src/**]]></sonar.exclusions>\n"))
    proc = stop(repo)
    check("sonar-gate: the same count with another value blocks: names and values are compared",
          proc.returncode == 2 and "xmllint: sonar.exclusions=gen/**,src/**" in proc.stderr
          and "audit:   sonar.exclusions=gen/**<![CDATA[,src/**]]>" in proc.stderr,
          f"exit {proc.returncode}, stderr {proc.stderr[:400]!r}")
    for name, text, want in [
        ("a key split over a continuation line is still its key",
         "sonar.projectName=x\n\nsonar.\\\n    exclusions=src/**\n",
         "web/sonar-project.properties:3: sonar.exclusions=src/**"),
        ("a lone carriage return ends a properties line",
         "sonar.projectName=x\n\nfoo=1\rsonar.exclusions=src/**\n", "sonar.exclusions=src/**"),
    ]:
        reset(repo)
        put(repo / "web/sonar-project.properties", text)
        proc = stop(repo)
        check(f"sonar-gate: {name}", proc.returncode == 2 and want in proc.stderr,
              f"exit {proc.returncode}, stderr {proc.stderr[:300]!r}")

    # The Maven scan analyses each pom, so a changed pom is listed for the gate.
    reset(repo)
    put(repo / "pom.xml", "<project><!-- TODO --></project>\n")
    before = len(calls())
    proc = stop(repo)
    check("sonar-gate: a changed pom is listed for the gate", calls()[before:] == [["pom.xml"]],
          f"exit {proc.returncode}, calls {calls()[before:]}")

    # A rule or a value taken out of the rules file narrows the gate: it needs a reason, written
    # in a comment added with the change.
    repo = new_repo("rules", "main")
    rules_text = "# java:S2 is noisy, a header says.\njava:S1\njava:S2 max=3\n"
    put(repo / ".sonar-gate", "rules = rules.txt\n")
    put(repo / "rules.txt", rules_text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "rules")
    rules_cases = [
        ("a rule taken out of the rules file blocks", rules_text.replace("java:S2 max=3\n", ""), 2,
         "rules.txt: java:S2 max=3 (taken out or changed)"),
        ("a value changed in the rules file blocks", rules_text.replace("max=3", "max=9"), 2,
         "rules.txt: java:S2 max=3 (taken out or changed)"),
        ("an old comment naming the rule justifies nothing", rules_text.replace("java:S1\n", ""), 2,
         "rules.txt: java:S1 (taken out or changed)"),
        ("a comment naming another rule that starts alike justifies nothing",
         rules_text.replace("java:S1\n", "# java:S10 goes: fixture reason\n"), 2,
         "rules.txt: java:S1 (taken out or changed)"),
        ("a new comment naming the rule justifies taking it out, and the report shows it",
         rules_text.replace("java:S2 max=3\n", "# java:S2 dropped: fixture reason\n"), 0,
         "(reason: java:S2 dropped: fixture reason)"),
        ("a rule commented out is not its own reason",
         rules_text.replace("java:S2 max=3\n", "# java:S2 max=3    # was here\n"), 2,
         "rules.txt: java:S2 max=3 (taken out or changed)"),
        ("a rule added to the rules file passes silently", rules_text + "java:S3\n", 0, ""),
        ("a rule added with parameters needs a reason: they may override Sonar way's",
         rules_text + "java:S3776 Threshold=1000\n", 2,
         "rules.txt: java:S3776 Threshold=1000 (added with parameters"),
        ("a rule added with parameters and its reason passes, and the report shows it",
         rules_text + "# java:S3776 at 1000: fixture reason\njava:S3776 Threshold=1000\n", 0,
         "(reason: java:S3776 at 1000: fixture reason)"),
    ]
    for name, text, want_exit, want in rules_cases:
        reset(repo)
        put(repo / "rules.txt", text)
        proc = stop(repo)
        where = proc.stderr if want_exit == 2 else shown(proc)
        check(f"sonar-gate: {name}",
              proc.returncode == want_exit and want in where and (want or proc.stdout == ""),
              f"exit {proc.returncode}, stdout {proc.stdout[:200]!r}, stderr {proc.stderr[:200]!r}")

    # .sonar-gate narrows the gate too: the JS project or the rules dropped, scope moved off
    # project, an IDE exclusion added. Each needs a reason written with the change.
    repo = new_repo("gate-file", "main")
    gate_text = "rules = rules.txt\njs-project = web\nscope = project\nide-exclusions = gen/**\n"
    put(repo / ".sonar-gate", gate_text)
    put(repo / "rules.txt", "java:S1\n")
    put(repo / "web/sonar-project.properties", "sonar.projectName=x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "gate settings")
    gate_cases = [
        ("dropping the JS project blocks", gate_text.replace("js-project = web\n", ""), 2,
         '.sonar-gate: js-project web is now ""'),
        ("dropping the rules file blocks", gate_text.replace("rules = rules.txt\n", ""), 2,
         '.sonar-gate: rules rules.txt is now ""'),
        ("moving scope off project blocks", gate_text.replace("scope = project", "scope = changed"),
         2, '.sonar-gate: scope project is now "changed"'),
        ("adding an IDE exclusion blocks", gate_text.replace("gen/**", "gen/**, src/**"), 2,
         ".sonar-gate: ide-exclusions adds src/**"),
        ("a new comment naming the setting justifies it, and the report shows it",
         "# js-project goes: fixture reason\n" + gate_text.replace("js-project = web\n", ""), 0,
         "(reason: js-project goes: fixture reason)"),
        ("commenting out the rules file is not its own reason",
         gate_text.replace("rules = rules.txt", "# rules = rules.txt"), 2,
         '.sonar-gate: rules rules.txt is now ""'),
        ("commenting out the JS project is not its own reason",
         gate_text.replace("js-project = web", "# js-project = web"), 2,
         '.sonar-gate: js-project web is now ""'),
        ("commenting out scope is not its own reason",
         gate_text.replace("scope = project", "# scope = project"), 2,
         '.sonar-gate: scope project is now ""'),
        ("a setting that widens passes silently",
         gate_text.replace("ide-exclusions = gen/**\n", ""), 0, ""),
    ]
    for name, text, want_exit, want in gate_cases:
        reset(repo)
        put(repo / ".sonar-gate", text)
        proc = stop(repo)
        where = proc.stderr if want_exit == 2 else shown(proc)
        check(f"sonar-gate: {name}",
              proc.returncode == want_exit and want in where and (want or proc.stdout == ""),
              f"exit {proc.returncode}, stdout {proc.stdout[:200]!r}, stderr {proc.stderr[:300]!r}")

    # The root pom's exclusions say nothing about the JS project's files.
    repo = new_repo("web-exempt", "main")
    put(repo / ".sonar-gate", "js-project = web\n")
    put(repo / "pom.xml", pom("    <!-- Generated code. -->\n"
                              "    <sonar.exclusions>**/gen/**</sonar.exclusions>\n"))
    put(repo / "web/sonar-project.properties", "sonar.projectName=x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "exclusions")
    put(repo / "web/src/gen/a.ts", "export const a = 1; // NOSONAR\n")
    proc = stop(repo)
    check("sonar-gate: the root pom's exclusions exempt no JS file from the NOSONAR audit",
          proc.returncode == 2 and "web/src/gen/a.ts:1:" in proc.stderr,
          f"exit {proc.returncode}, stderr {proc.stderr[:300]!r}")

    # Every changed source file goes to the gate as --indexed, which refuses one its latest analysis
    # holds no component for; Java the base's root pom excludes carries a generator's header instead.
    repo = new_repo("indexed", "main")
    put(repo / ".sonar-gate", "js-project = web\n")
    put(repo / "pom.xml", pom("    <!-- Generated code. -->\n"
                              "    <sonar.exclusions>**/gen/**</sonar.exclusions>\n"))
    put(repo / "web/sonar-project.properties", "sonar.projectName=x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "web and exclusions")
    sources = ["backend/pom.xml", "backend/src/main/java/Api.java", "src/test/java/AppTest.java",
               app, "web/src/a.ts", "web/src/b.css", "web/vitest.config.mts"]
    others = ["src/test/resources/Fixture.java", "web/src/global.d.ts", "web/README.md",
              "web/package.json"]
    for path in sources + others:
        put(repo / path, "class X {}\n" if path.endswith(".java")
            else "<project/>\n" if path.endswith("pom.xml") else "x\n")
    put(repo / "backend/src/main/gen/G.java", "// Code generated by a fixture.\nclass G {}\n")
    before = len(indexed_calls())
    proc = stop(repo)
    check("sonar-gate: changed code kept out of analysis is shown to the user, with its header",
          "backend/src/main/gen/G.java: kept out of analysis by the root pom's sonar.exclusions "
          "(header: // Code generated by a fixture.)" in shown(proc), repr(proc.stdout[:300]))
    check("sonar-gate: Java under src/main|test/java, poms and the JS project's code go to the gate "
          "as --indexed; resources, .d.ts, prose, JSON and generated Java do not",
          proc.returncode == 0
          and [sorted(c) for c in indexed_calls()[before:]] == [sorted(sources)],
          f"exit {proc.returncode}, indexed {indexed_calls()[before:]}, stderr {proc.stderr[:200]!r}")
    put(repo / ".sonar-gate", "js-project = web\nscope = project\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "whole project")
    put(repo / app, "class App { int whole; }\n")
    before = len(calls())
    proc = stop(repo)
    check("sonar-gate: scope = project lists the changed sources as --indexed, with no --files",
          proc.returncode == 0 and calls()[before:] == [[]] and indexed_calls()[-1:] == [[app]],
          f"exit {proc.returncode}, calls {calls()[before:]}, indexed {indexed_calls()[-1:]}")

    # A gate that would outlast Claude Code's hook timeout is stopped first, Maven and all, and
    # the user is told.
    repo = new_repo("slow", "main")
    put(repo / app, "class App { int slow; }\n")
    finished = fx / "slow-gate-finished"
    started = time.monotonic()
    proc = stop(repo, CLAUDE_SONAR_GATE_TIMEOUT="1", STUB_GATE_SLEEP="4",
                STUB_GATE_FINISHED=str(finished))
    elapsed = time.monotonic() - started
    time.sleep(5)
    check("sonar-gate: a gate past its time is stopped, the user told, and nothing outlives it",
          proc.returncode == 0 and "stopped after 1s" in shown(proc) and elapsed < 4
          and not finished.exists(),
          f"exit {proc.returncode}, {elapsed:.1f}s, finished {finished.exists()}, "
          f"stdout {proc.stdout[:200]!r}")

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
printf '%s\\n' "$*" >>"${STUB_ARGV_LOG:-/dev/null}"
printf 'opts=%s tool=%s jdk=%s underscore=%s\\n' "${MAVEN_OPTS-unset}" "${JAVA_TOOL_OPTIONS-unset}" \\
  "${JDK_JAVA_OPTIONS-unset}" "${_JAVA_OPTIONS-unset}" >>"${STUB_MVNW_ENV_LOG:-/dev/null}"
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
printf '%s\n' "$*" >>"${STUB_ARGV_LOG:-/dev/null}"
case " $* " in *" -K - "*) cat >/dev/null ;; esac
page=1
lang=""
key=""
for a in "$@"; do
  case "$a" in
    p=*) page=${a#p=} ;;
    language=*) lang=${a#language=} ;;
    component=* | key=* | project=* | projectKey=*) key=${a#*=} ;;
  esac
done
project=${key%%:*}
issues() { # $1 total, $2 count, $3 path, $4 rule, [$5 project key], [$6 issue status]
  /usr/bin/jq -n --argjson t "$1" --argjson n "$2" --arg f "$3" --arg r "$4" \
    --arg k "${5:-local-project}" --arg s "${6:-OPEN}" \
    '{paging: {total: $t}, issues: [range($n) | {component: ($k + ":" + $f),
      rule: $r, message: "fixture", line: 7, issueStatus: $s}]}'
}
# One profile per language, as the server answers a project's: ours where STUB_ASSIGNED says pf,
# the built-in Sonar way otherwise, and xml on STUB_XML_PROFILE.
project_profiles() {
  /usr/bin/jq -n -c --arg assigned "${STUB_ASSIGNED:-pf}" --arg lang "$lang" \
    --arg xml "${STUB_XML_PROFILE:-Sonar way}" --arg updated "${STUB_RULES_UPDATED:-t1}" '
    [ {language: "java", key: $assigned,
       name: (if $assigned == "pf" then "ruled way" else "Sonar way" end),
       isBuiltIn: ($assigned != "pf"), rulesUpdatedAt: $updated},
      {language: "xml", key: "xml-profile", name: $xml, isBuiltIn: ($xml == "Sonar way"),
       rulesUpdatedAt: $updated} ]
    | {profiles: map(select($lang == "" or .language == $lang))}'
}
case "$*" in
  */api/system/status*) echo '{"status":"UP"}' ;;
  */api/server/version*) echo "${STUB_SERVER_VERSION:-26.8}" ;;
  */api/qualityprofiles/search*)
    case "$*" in
      *"qualityProfile=Sonar way"*)
        printf '{"profiles":[{"key":"sw","name":"Sonar way","language":"%s","isBuiltIn":true}]}\n' "$lang" ;;
      *qualityProfile=*)
        if [ -n "${STUB_PROFILE:-}" ]; then
          printf '{"profiles":[{"key":"pf","name":"ruled way","language":"%s","parentKey":"%s"}]}\n' \
            "$lang" "${STUB_PARENT:-sw}"
        else
          echo '{"profiles":[]}'
        fi ;;
      *) project_profiles ;;
    esac ;;
  */api/rules/search*)
    case "$*" in
      *qprofile=sw*) actives="${STUB_PARENT_ACTIVES:-}" ;;
      *) actives="${STUB_ACTIVES:-}" ;;
    esac
    [ -n "$actives" ] || actives='{}'
    rules="${STUB_RULES:-}"
    [ -n "$rules" ] || rules='[{"key":"x"}]'
    printf '{"total":1,"rules":%s,"actives":%s}\n' "$rules" "$actives" ;;
  */api/settings/values*)
    case "$*" in
      *component=*) settings="${STUB_SETTINGS:-}" ;;
      *) settings="${STUB_INSTANCE_SETTINGS:-}" ;;
    esac
    [ -n "$settings" ] || settings='{"settings":[]}'
    echo "$settings" ;;
  */api/project_analyses/search*)
    latest="${STUB_ANALYSIS:-a1}"
    if [ -n "${STUB_ANALYSIS_AFTER_READ:-}" ] && [ -e "${STUB_READ_MARK:-/nonexistent}" ]; then
      latest="$STUB_ANALYSIS_AFTER_READ"
    fi
    printf '{"analyses":[{"key":"%s"}]}\n' "$latest" ;;
  */api/measures/component_tree*)
    case "${STUB_DUPS:-}" in
      one) /usr/bin/jq -n -c --arg k "$project" --arg f "${STUB_DUP_PATH:-src/main/java/App.java}" \
             '{paging: {total: 1}, components: [{key: ($k + ":" + $f),
               measures: [{metric: "duplicated_blocks", value: "1"}]}]}' ;;
      *) echo '{"paging":{"total":0},"components":[]}' ;;
    esac ;;
  */api/components/tree*)
    /usr/bin/jq -n -c --arg k "$project" --arg files "${STUB_COMPONENTS:-}" '
      ($files | split(",") | map(select(length > 0))) as $f
      | {paging: {total: ($f | length)}, components: [$f[] | {key: ($k + ":" + .)}]}' ;;
  */api/duplications/show*)
    /usr/bin/jq -n -c --arg self "$key" \
      --arg other "$project:${STUB_DUP_PARTNER:-src/main/java/Other.java}" \
      '{duplications: [{blocks: [{from: 3, size: 10, _ref: "1"}, {from: 20, size: 10, _ref: "2"}]}],
        files: {"1": {key: $self}, "2": {key: $other}}}' ;;
  */api/hotspots/search*)
    case "${STUB_HOTSPOTS:-}" in
      two) /usr/bin/jq -n -c --arg k "$project" '{paging: {total: 2}, hotspots: [
             {component: ($k + ":src/main/java/App.java"), line: 9, message: "fixture hotspot",
              ruleKey: "java:S2245", status: "TO_REVIEW"},
             {component: ($k + ":src/main/java/App.java"), line: 11, message: "fixture safe",
              ruleKey: "java:S2245", status: "REVIEWED", resolution: "SAFE"},
             {component: ($k + ":src/Other.java"), line: 3, message: "fixture elsewhere",
              ruleKey: "java:S2245", status: "TO_REVIEW"}]}' ;;
      *) echo '{"paging":{"total":0},"hotspots":[]}' ;;
    esac ;;
  */api/ce/task*)
    printf '{"task":{"status":"%s","analysisId":"%s"}}\n' "$STUB_CE_STATUS" "${STUB_ANALYSIS:-a1}" ;;
  */api/issues/search*)
    [ -z "${STUB_READ_MARK:-}" ] || : >"$STUB_READ_MARK"
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
      web:*) issues 1 1 src/a.ts typescript:S1 local-mixed-web ;;
      accepted:*)
        case "$*" in
          *issueStatuses=*ACCEPTED*) issues 1 1 src/main/java/App.java java:S2 local-project ACCEPTED ;;
          *) echo '{"paging":{"total":0},"issues":[]}' ;;
        esac ;;
      false-positive:*)
        case "$*" in
          *issueStatuses=*FALSE_POSITIVE*) issues 1 1 src/main/java/App.java java:S2 local-project FALSE_POSITIVE ;;
          *) echo '{"paging":{"total":0},"issues":[]}' ;;
        esac ;;
      *) echo '{"paging":{"total":0},"issues":[]}' ;;
    esac ;;
  *) exit 7 ;;
esac
"""
STUB_NPX = """#!/bin/bash
printf '%s\\n' "$*" >>"${STUB_ARGV_LOG:-/dev/null}"
printf 'npx\\n' >>"${STUB_NPX_LOG:-/dev/null}"
printf 'cwd=%s json=%s prefixed=%s tool=%s\\n' "$PWD" "${SONAR_SCANNER_JSON_PARAMS-unset}" \\
  "${SONAR_SCANNER_SONAR_EXCLUSIONS-unset}" "${JAVA_TOOL_OPTIONS-unset}" >>"${STUB_NPX_ENV_LOG:-/dev/null}"
for a in "$@"; do case "$a" in -Dsonar.working.directory=*) work=${a#*=} ;; esac; done
if [ -n "${STUB_CE:-}" ] && [ -n "${work:-}" ]; then
  mkdir -p "$work"
  printf 'ceTaskId=%s\\n' "$STUB_CE" >"$work/report-task.txt"
fi
exit 0
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
                       (stubs / "npx", STUB_NPX), (stubs / "sleep", "#!/bin/bash\n")):
        path.write_text(text)
        path.chmod(0o755)
    env = {**os.environ, "PATH": f"{stubs}:{mktemp_env['PATH']}", "TMPDIR": str(tmp),
           "STUB_MKTEMP_LOG": mktemp_env["STUB_MKTEMP_LOG"],
           "SONAR_TOKEN": "fixture-analysis-secret", "SONAR_ADMIN_TOKEN": "fixture-admin-secret",
           "SONAR_HOST_URL": "http://sonar.invalid", "STUB_ARGV_LOG": str(fx / "argv.log")}
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

    def gate(where: Path, *extra: str, **stub: str) -> subprocess.CompletedProcess:
        return subprocess.run([SONAR_GATE, "--project-dir", str(where), "--no-boot", *extra],
                              capture_output=True, text=True, timeout=60, check=False,
                              env={**env, "STUB_CE": "task-1", "STUB_CE_STATUS": "SUCCESS",
                                   **stub})

    def output(proc: subprocess.CompletedProcess) -> str:
        return f"exit {proc.returncode}, output {(proc.stdout + proc.stderr).strip()[-240:]!r}"

    def project_dir(name: str, gate_settings: str = "", git: bool = False) -> Path:
        where = fx / name
        where.mkdir()
        (where / "pom.xml").write_text("<project/>\n")
        (where / ".gitignore").write_text("target/\n")
        (where / "mvnw").write_text(STUB_MVNW)
        (where / "mvnw").chmod(0o755)
        if gate_settings:
            (where / ".sonar-gate").write_text(gate_settings)
        if "js-project = web" in gate_settings:
            (where / "web/src").mkdir(parents=True)
            (where / "web/sonar-project.properties").write_text("sonar.sources=.\n")
            (where / "web/src/a.ts").write_text("export const a = 1;\n")
        if git:
            git_in(where, "init", "-q")
            git_in(where, "add", "-A")
            git_in(where, "commit", "-q", "-m", "x")
        return where

    git_env = {**env, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}

    def git_in(where: Path, *args: str) -> None:
        subprocess.run(["git", "-C", str(where), "-c", "user.name=f",
                        "-c", "user.email=f@example.invalid", *args],
                       check=True, capture_output=True, env=git_env)

    argv_log, npx_log = fx / "argv.log", fx / "npx.log"

    def builds() -> tuple[int, int]:
        maven = argv_log.read_text().count("clean test-compile") if argv_log.exists() else 0
        npx = npx_log.read_text().count("npx") if npx_log.exists() else 0
        return maven, npx

    proc = gate(project, *files, STUB_DUPS="one")
    check("sonar-gate.sh: a duplicated block in a listed file is a finding, with its partner",
          proc.returncode == 2 and "src/main/java/App.java:3 [duplication] 10 lines duplicated "
          "at src/main/java/Other.java:20" in proc.stdout, output(proc))
    for status, issues in (("ACCEPTED", "accepted"), ("FALSE_POSITIVE", "false-positive")):
        proc = gate(project, *files, STUB_ISSUES=issues)
        check(f"sonar-gate.sh: an issue marked {status} on the server still counts, and says so",
              proc.returncode == 2
              and f"App.java:7 [java:S2] fixture (marked {status}" in proc.stdout, output(proc))

    proc = gate(project, *files, STUB_HOTSPOTS="two")
    check("sonar-gate.sh: a security hotspot in a listed file is a finding, a reviewed one too, "
          "and one elsewhere is not",
          proc.returncode == 2
          and "App.java:9 [java:S2245] security hotspot: fixture hotspot" in proc.stdout
          and "App.java:11 [java:S2245] security hotspot: fixture safe (reviewed SAFE" in proc.stdout
          and "fixture elsewhere" not in proc.stdout, output(proc))
    mvnw_env = fx / "mvnw-env.log"
    proc = gate(project, *files, MAVEN_OPTS="-Dsonar.exclusions=**/*",
                JAVA_TOOL_OPTIONS="-Dsonar.java.file.suffixes=.none",
                JDK_JAVA_OPTIONS="-Dsonar.exclusions=**/*", _JAVA_OPTIONS="-Dsonar.exclusions=**/*",
                STUB_MVNW_ENV_LOG=str(mvnw_env))
    check("sonar-gate.sh: Maven runs without MAVEN_OPTS or the JVM's option variables, which "
          "could carry Sonar properties",
          mvnw_env.exists() and set(mvnw_env.read_text().split())
          == {"opts=unset", "tool=unset", "jdk=unset", "underscore=unset"},
          mvnw_env.read_text() if mvnw_env.exists() else "mvnw never ran")

    # --indexed: a listed file the latest analysis holds no component for is a finding.
    indexed = fx / "indexed.txt"
    indexed.write_text("src/main/java/App.java\npom.xml\n")
    proc = gate(project, *files, "--indexed", str(indexed), STUB_COMPONENTS="src/main/java/App.java")
    check("sonar-gate.sh: an --indexed file missing from the analysis is a finding",
          proc.returncode == 2 and "pom.xml:0 [not-analysed] Sonar did not analyse this file"
          in proc.stdout and "App.java:0" not in proc.stdout, output(proc))
    proc = gate(project, *files, "--indexed", str(indexed),
                STUB_COMPONENTS="src/main/java/App.java,pom.xml")
    check("sonar-gate.sh: --indexed files all in the analysis leave it clean",
          proc.returncode == 0 and "clean" in proc.stderr, output(proc))

    # A TypeScript project beside the Maven one: its own key, its paths under its directory, and
    # no Maven build when only its files are listed.
    mixed = project_dir("mixed", "js-project = web\n")
    web_files = fx / "web-files.txt"
    web_files.write_text("web/src/a.ts\n")
    before = builds()
    proc = gate(mixed, "--files", str(web_files), STUB_ISSUES="web", STUB_NPX_LOG=str(npx_log))
    check("sonar-gate.sh: a TypeScript finding is reported under the project's directory",
          proc.returncode == 2 and "web/src/a.ts:7 [typescript:S1]" in proc.stdout, output(proc))
    check("sonar-gate.sh: listing only TypeScript files scans with npx and builds no Maven",
          builds() == (before[0], before[1] + 1), f"{before} -> {builds()}")
    npx_env = fx / "npx-env.log"
    gate(mixed, "--files", str(web_files), STUB_NPX_LOG=str(npx_log), STUB_NPX_ENV_LOG=str(npx_env),
         SONAR_SCANNER_JSON_PARAMS='{"sonar.exclusions":"**/*"}',
         SONAR_SCANNER_SONAR_EXCLUSIONS="**/*")
    seen = npx_env.read_text() if npx_env.exists() else ""
    check("sonar-gate.sh: the npm scanner gets no SONAR_SCANNER variable and runs outside the "
          "project, so no project .npmrc reaches it",
          "json=unset prefixed=unset" in seen and f"cwd={mixed / 'web'}" not in seen
          and f"-Dsonar.projectBaseDir={mixed / 'web'}" in argv_log.read_text(), seen)
    gate(mixed, "--files", str(web_files), STUB_NPX_LOG=str(npx_log), STUB_NPX_ENV_LOG=str(npx_env),
         JAVA_TOOL_OPTIONS="-Dsonar.exclusions=**/*")
    seen = npx_env.read_text() if npx_env.exists() else ""
    check("sonar-gate.sh: the npm scanner's JVM gets no JAVA_TOOL_OPTIONS, and SonarJS no "
          "generated-code detection, which a codegen manifest in the repository could steer",
          seen.splitlines()[-1:] and seen.splitlines()[-1].endswith("tool=unset")
          and "-Dsonar.javascript.detectGeneratedCode=false" in argv_log.read_text(), seen)
    proc = gate(mixed, "--files", str(web_files), STUB_DUPS="one", STUB_DUP_PATH="src/a.ts",
                STUB_DUP_PARTNER="src/b.ts", STUB_NPX_LOG=str(npx_log))
    check("sonar-gate.sh: a TypeScript duplication is reported under the project's directory",
          proc.returncode == 2
          and "web/src/a.ts:3 [duplication] 10 lines duplicated at web/src/b.ts:20" in proc.stdout,
          output(proc))

    # The repository's rule set is checked against the server on every run, before any scan.
    ruled = project_dir("ruled", "rules = rules.txt\n")
    (ruled / "rules.txt").write_text("java:S1 max=3    # a fixture rule\n")
    defaults = ('[{"key":"java:S1","params":[{"key":"max","defaultValue":"5"},'
                '{"key":"min","defaultValue":"0"}]},{"key":"java:S2"},{"key":"java:S7"},'
                '{"key":"java:S9"}]')

    def activation(rule: str, inherit: str = "NONE", profile: str = "pf", **params: str) -> str:
        values = ",".join(f'{{"key":"{k}","value":"{v}"}}' for k, v in params.items())
        return f'"{rule}":[{{"qProfile":"{profile}","inherit":"{inherit}","params":[{values}]}}]'

    match = activation("java:S1", max="3", min="0")
    ruled_stub = {"STUB_PROFILE": "1", "STUB_RULES": defaults}
    drift_cases = [
        ("refuses to answer while a listed rule is inactive, naming --provision", {}, 1,
         ["activate java:S1", "--provision", "owner decides"]),
        ("names an override of a Sonar way rule, with its values",
         {"STUB_PARENT_ACTIVES": "{" + activation("java:S1", profile="sw", max="5", min="0") + "}",
          "STUB_ACTIVES": "{" + activation("java:S1", "INHERITED", max="5", min="0") + "}"}, 1,
         ["override java:S1 max=3", "other parameters (override)"]),
        ("refuses a listed value changed on the server",
         {"STUB_ACTIVES": "{" + activation("java:S1", max="4", min="0") + "}"}, 1,
         ["activate java:S1"]),
        ("refuses a parameter the file leaves at its default, loosened on the server",
         {"STUB_ACTIVES": "{" + activation("java:S1", max="3", min="-100") + "}"}, 1,
         ["activate java:S1"]),
        ("refuses a rule the profile adds and the file does not list",
         {"STUB_ACTIVES": "{" + match + "," + activation("java:S9") + "}"}, 1,
         ["deactivate java:S9"]),
        ("refuses an inherited rule whose parameters the profile overrides",
         {"STUB_ACTIVES": "{" + match + "," + activation("java:S7", "OVERRIDES") + "}"}, 1,
         ["reset java:S7"]),
        ("refuses a rule of Sonar way the profile deactivated",
         {"STUB_ACTIVES": "{" + match + "}",
          "STUB_PARENT_ACTIVES": "{" + activation("java:S2", profile="sw") + "}"}, 1,
         ["reactivate java:S2"]),
        ("ignores another profile's activations",
         {"STUB_ACTIVES": "{" + activation("java:S1", profile="other", max="3", min="0") + "}"}, 1,
         ["activate java:S1"]),
        ("refuses a profile that is not a child of Sonar way",
         {"STUB_ACTIVES": "{" + match + "}", "STUB_PARENT": "elsewhere"}, 1, ["not a child"]),
        ("refuses a project on another profile for a rules language",
         {"STUB_ACTIVES": "{" + match + "}", "STUB_ASSIGNED": "sw"}, 1,
         ['java does not use "ruled way"']),
        ("refuses a project on a custom profile for another language",
         {"STUB_ACTIVES": "{" + match + "}", "STUB_XML_PROFILE": "lenient"}, 1,
         ["xml uses lenient"]),
        ("refuses any setting of a project key's own, narrowing or not",
         {"STUB_ACTIVES": "{" + match + "}",
          "STUB_SETTINGS": '{"settings":[{"key":"sonar.javascript.maxFileSize","value":"1",'
                           '"inherited":false}]}'}, 1,
         ["set sonar.javascript.maxFileSize"]),
        ("refuses a narrowing setting at instance level, where it reaches every project",
         {"STUB_ACTIVES": "{" + match + "}",
          "STUB_INSTANCE_SETTINGS": '{"settings":[{"key":"sonar.global.exclusions",'
                                    '"values":["**/*"],"inherited":false}]}'}, 1,
         ["sonar.global.exclusions", "the owner decides"]),
        ("ignores an instance setting the allowlist holds",
         {"STUB_ACTIVES": "{" + match + "}",
          "STUB_INSTANCE_SETTINGS": '{"settings":[{"key":"sonar.core.serverBaseURL",'
                                    '"value":"x","inherited":false}]}'}, 0, ["clean"]),
        ("refuses any other instance setting, whatever its name says",
         {"STUB_ACTIVES": "{" + match + "}",
          "STUB_INSTANCE_SETTINGS": '{"settings":[{"key":"sonar.cpd.java.minimumTokens",'
                                    '"value":"1000","inherited":false}]}'}, 1,
         ["sonar.cpd.java.minimumTokens", "INSTANCE_ALLOWED"]),
        ("refuses a narrowing setting on a project key",
         {"STUB_ACTIVES": "{" + match + "}",
          "STUB_SETTINGS": '{"settings":[{"key":"sonar.coverage.exclusions","values":["**/*"],'
                           '"inherited":false}]}'}, 1,
         ["set sonar.coverage.exclusions"]),
        ("ignores a narrowing setting inherited from the instance",
         {"STUB_ACTIVES": "{" + match + "}",
          "STUB_SETTINGS": '{"settings":[{"key":"sonar.javascript.exclusions","values":["x"],'
                           '"inherited":true}]}'}, 0, ["clean"]),
        ("answers once the server matches the repository, inherited rules included",
         {"STUB_ACTIVES": "{" + match + "," + activation("java:S2", "INHERITED") + "}",
          "STUB_PARENT_ACTIVES": "{" + activation("java:S2", profile="sw") + "}"}, 0, ["clean"]),
    ]
    for name, stub, want_exit, wants in drift_cases:
        proc = gate(ruled, **ruled_stub, **stub)
        check(f"sonar-gate.sh: {name}",
              proc.returncode == want_exit and all(w in proc.stdout + proc.stderr for w in wants),
              output(proc))
    proc = gate(ruled)
    check("sonar-gate.sh: refuses to answer when the server has no profile for the rules",
          proc.returncode == 1 and "--provision" in proc.stderr, output(proc))
    for name, stub, wants in [
        ("a project key's own setting",
         {"STUB_SETTINGS": '{"settings":[{"key":"sonar.exclusions","values":["**/*"],'
                           '"inherited":false}]}'}, ["set sonar.exclusions", "(.sonar-gate)"]),
        ("an instance setting",
         {"STUB_INSTANCE_SETTINGS": '{"settings":[{"key":"sonar.global.exclusions",'
                                    '"values":["**/*"],"inherited":false}]}'},
         ["sonar.global.exclusions"]),
    ]:
        proc = gate(project, *files, **stub)
        check(f"sonar-gate.sh: without a rules file, still refuses {name}",
              proc.returncode == 1 and all(w in proc.stderr for w in wants), output(proc))
    (ruled / ".sonar-gate").write_text("rules = rules.txt\nide-exclusions = gen/**, b/**\n")
    ide_set = ('{"settings":[{"key":"sonar.exclusions","values":["gen/**","b/**"],'
               '"inherited":false}]}')
    proc = gate(ruled, **ruled_stub, STUB_ACTIVES="{" + match + "}", STUB_SETTINGS=ide_set)
    check("sonar-gate.sh: refuses the IDE's exclusions while the root pom sets none to keep them "
          "out of the gate's Maven scan",
          proc.returncode == 1 and "root pom sets no sonar.exclusions" in proc.stderr, output(proc))
    (ruled / "pom.xml").write_text("<project><properties><sonar.exclusions>gen/**"
                                   "</sonar.exclusions></properties></project>\n")
    proc = gate(ruled, **ruled_stub, STUB_ACTIVES="{" + match + "}")
    check("sonar-gate.sh: refuses a key that lacks the IDE's exclusions .sonar-gate gives it",
          proc.returncode == 1 and "missing sonar.exclusions" in proc.stderr, output(proc))
    proc = gate(ruled, **ruled_stub, STUB_ACTIVES="{" + match + "}",
                STUB_SETTINGS=ide_set.replace("]}", ',{"key":"sonar.test.exclusions",'
                                                    '"values":["gen/**"],"inherited":false}]}'))
    check("sonar-gate.sh: refuses the IDE's exclusions as test exclusions, which would reach the "
          "gate's scan of the Java tests",
          proc.returncode == 1 and "set sonar.test.exclusions" in proc.stderr, output(proc))
    proc = gate(ruled, **ruled_stub, STUB_ACTIVES="{" + match + "}", STUB_SETTINGS=ide_set)
    check("sonar-gate.sh: answers once the key carries the IDE's exclusions",
          proc.returncode == 0, output(proc))

    # A project whose inputs match its last analysis from here is read, not rebuilt, and only
    # what changed is rebuilt.
    fresh = project_dir("fresh", "js-project = web\n", git=True)
    stub = {"STUB_NPX_LOG": str(npx_log)}

    steps = [
        ("a first run builds both projects", None, {}, (1, 1)),
        ("an unchanged run builds nothing", None, {}, (0, 0)),
        ("an edited pom rebuilds Maven alone",
         lambda: (fresh / "pom.xml").write_text("<project><!-- x --></project>\n"), {}, (1, 0)),
        ("an edited TypeScript file rebuilds the web project alone",
         lambda: (fresh / "web/src/a.ts").write_text("export const a = 2;\n"), {}, (0, 1)),
        ("an untracked file rebuilds its project",
         lambda: (fresh / "src").mkdir() or (fresh / "src/New.java").write_text("class N {}\n"),
         {}, (1, 0)),
        ("a commit rebuilds both", lambda: (git_in(fresh, "add", "-A"),
                                            git_in(fresh, "commit", "-q", "-m", "y")), {}, (1, 1)),
        ("another analysis on the server rebuilds both", None, {"STUB_ANALYSIS": "a2"}, (1, 1)),
        ("a profile changed on the server rebuilds both", None,
         {"STUB_ANALYSIS": "a2", "STUB_RULES_UPDATED": "t2"}, (1, 1)),
        ("a server upgrade rebuilds both", None,
         {"STUB_ANALYSIS": "a2", "STUB_RULES_UPDATED": "t2", "STUB_SERVER_VERSION": "27.1"}, (1, 1)),
        ("and then nothing", None,
         {"STUB_ANALYSIS": "a2", "STUB_RULES_UPDATED": "t2", "STUB_SERVER_VERSION": "27.1"}, (0, 0)),
    ]
    for name, change, extra_stub, want in steps:
        if change:
            change()
        before = builds()
        gate(fresh, **stub, **extra_stub)
        after = builds()
        got = (after[0] - before[0], after[1] - before[1])
        check(f"sonar-gate.sh: {name}", got == want, f"built {got}, expected {want}")

    proc = gate(fresh, **stub, STUB_ANALYSIS="a2", STUB_RULES_UPDATED="t2",
                STUB_SERVER_VERSION="27.1", STUB_ANALYSIS_AFTER_READ="a9",
                STUB_READ_MARK=str(fx / "issues-read"))
    check("sonar-gate.sh: refuses findings read while another analysis landed",
          proc.returncode == 1 and "landed while its findings were read" in proc.stderr,
          output(proc))

    leaked = [t for t in ("fixture-analysis-secret", "fixture-admin-secret")
              if t in argv_log.read_text()]
    check("sonar-gate.sh: no token ever reaches a command line", not leaked, repr(leaked))
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


# ── validate-rules.sh ───────────────────────────────────────────────────────
# The inflated body runs first as the positive control: a validator that never reached its
# oracle would pass every green case after it. The oracle is SESSION_RULES, so a candidate
# session-rules.sh is exercised here too.
def test_validate_rules() -> None:
    fx = Path(tempfile.mkdtemp()).resolve()
    config = fx / "config"
    copy_rules(config)
    frontend, java = config / "conventions" / "frontend.md", config / "conventions" / "java.md"
    java_stub = config / "rules" / "java.md"
    scratch = fx / "tmp"
    scratch.mkdir()
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(config), "CLAUDE_SESSION_RULES": SESSION_RULES,
           "TMPDIR": str(scratch)}
    silent = fx / "silent-oracle.sh"
    silent.write_text("#!/bin/bash\nexit 0\n")
    reworded = fx / "reworded-oracle.sh"
    oracle_src = Path(SESSION_RULES).read_text()
    check("validate-rules: the reworded oracle really differs from the real one",
          "exceeds" in oracle_src, "the notice no longer says 'exceeds'; update the mutant")
    reworded.write_text(oracle_src.replace("exceeds", "is over"))
    for stub in (silent, reworded):
        stub.chmod(0o755)

    def validate(*args: str, run_env: dict = env) -> subprocess.CompletedProcess:
        return subprocess.run([VALIDATE_RULES, *args], capture_output=True, text=True,
                              env=run_env, cwd=config, timeout=30, check=False)

    def detail(proc: subprocess.CompletedProcess) -> str:
        return f"exit {proc.returncode}, stderr {proc.stderr.strip()[:200]!r}"

    live, java_live, stub_live = frontend.read_text(), java.read_text(), java_stub.read_text()
    loop_heading = "\n### Self-review loop\n"
    frontend.write_text(live.replace(loop_heading, "\n" + "x" * 12000 + "\n" + loop_heading))
    proc = validate(str(frontend))
    check("validate-rules: positive control, an inflated body blocks and is named",
          proc.returncode == 2 and "conventions/frontend.md is too big" in proc.stderr,
          detail(proc))
    proc = validate("conventions/frontend.md")
    check("validate-rules: a relative path is checked", proc.returncode == 2, detail(proc))
    proc = validate(str(config / "rules" / "frontend.md"))
    check("validate-rules: a changed stub re-checks its body", proc.returncode == 2,
          detail(proc))
    proc = validate(str(frontend), run_env={**env, "CLAUDE_SESSION_RULES": str(reworded)})
    check("validate-rules: an overflow blocks whatever the oracle's notice says",
          proc.returncode == 2 and "conventions/frontend.md" in proc.stderr, detail(proc))
    frontend.write_text(live)
    proc = validate(str(config / "hooks" / "session-rules.sh"),
                    run_env={**env, "CLAUDE_SESSION_RULES": str(silent)})
    check("validate-rules: a change to the oracle re-checks every body",
          proc.returncode == 1 and all(f"session-rules.sh {path.stem} gave no injection"
                                       in proc.stderr
                                       for path in (config / "conventions").glob("*.md")),
          detail(proc))

    everything = [str(path) for sub in ("rules", "conventions")
                  for path in (config / sub).glob("*.md")]
    proc = validate(*everything)
    check("validate-rules: the live bodies and stubs pass", proc.returncode == 0 and not proc.stderr,
          detail(proc))

    stub_rows = [
        ("a stub without paths: blocks", stub_live.replace("paths:", "globs:"), "no paths:"),
        ("a stub without its marker blocks", stub_live.replace("[rule-stub java] ", ""),
         "does not start with [rule-stub java]"),
        ("a stub marked for another rule blocks",
         stub_live.replace("[rule-stub java]", "[rule-stub kotlin]"),
         "does not start with [rule-stub java]"),
        ("a stub that does not name its body blocks",
         stub_live.replace("~/.claude/conventions/java.md", "the Java body"), "does not name"),
        ("a stub over the cap blocks", stub_live + "y" * 600, "a stub stays under"),
    ]
    for name, text, message in stub_rows:
        check(f"validate-rules: the mutant for '{name}' differs from the live stub",
              text != stub_live, name)
        java_stub.write_text(text)
        proc = validate(str(java_stub))
        check(f"validate-rules: {name}", proc.returncode == 2 and message in proc.stderr,
              detail(proc))
    java_stub.unlink()
    proc = validate(str(java_stub))
    check("validate-rules: a deleted stub blocks while its body remains",
          proc.returncode == 2 and "rules/java.md is missing" in proc.stderr, detail(proc))
    java_stub.write_text(stub_live)
    java.unlink()
    proc = validate(str(java))
    check("validate-rules: a deleted body blocks while its stub remains",
          proc.returncode == 2 and "which does not exist" in proc.stderr, detail(proc))
    java_stub.unlink()
    proc = validate(str(java), str(java_stub))
    check("validate-rules: a body retired with its stub passes", proc.returncode == 0,
          detail(proc))
    java.write_text(java_live)
    java_stub.write_text(stub_live)

    kotlin, kotlin_stub = config / "conventions" / "kotlin.md", config / "rules" / "kotlin.md"
    kotlin.write_text("# Kotlin conventions\n" + live[live.index(loop_heading):])
    kotlin_stub.write_text(stub_live.replace("java", "kotlin"))
    proc = validate(str(kotlin))
    check("validate-rules: a body without a fixture row blocks",
          proc.returncode == 2 and "conventions/kotlin.md has no fixture row" in proc.stderr,
          detail(proc))
    kotlin.unlink()
    kotlin_stub.unlink()

    drifted = live.replace("adding nothing new.", "adding nothing.")
    check("validate-rules: the drifted loop really differs from the live one", drifted != live,
          "'adding nothing new.' is gone from the loop; update the mutant")
    frontend.write_text(drifted)
    proc = validate(str(java))
    check("validate-rules: a loop edited in one body blocks, naming the difference",
          proc.returncode == 2 and "differ" in proc.stderr and "adding nothing" in proc.stderr,
          detail(proc))
    proc = validate(str(frontend), run_env={**env, "CLAUDE_SESSION_RULES": str(fx / "missing.sh")})
    check("validate-rules: loop drift still blocks when the size check is OFF",
          proc.returncode == 2 and "OFF" in proc.stderr and "differ" in proc.stderr, detail(proc))
    proc = validate(str(frontend), run_env={**env, "TMPDIR": str(fx / "no-such-dir")})
    check("validate-rules: loop drift still blocks when no fixture directory can be made",
          proc.returncode == 2 and "OFF" in proc.stderr and "differ" in proc.stderr, detail(proc))
    for body in (config / "conventions").glob("*.md"):
        body.write_text(body.read_text().replace(loop_heading, "\n### Review loop\n"))
    proc = validate(str(frontend))
    check("validate-rules: a loop missing from every body blocks rather than passing as equal",
          proc.returncode == 2 and all(f"conventions/{path.name} has no" in proc.stderr
                                       for path in (config / "conventions").glob("*.md")),
          detail(proc))
    for path in (ROOT / "conventions").glob("*.md"):
        shutil.copy(path, config / "conventions" / path.name)
    proc = validate(str(config / "README.md"), "/etc/hosts", str(config / "rules" / "shell.md"),
                    run_env={**env, "CLAUDE_SESSION_RULES": str(fx / "missing.sh")})
    check("validate-rules: other paths, shell.md included, pass without running the oracle",
          proc.returncode == 0 and not proc.stderr, detail(proc))
    proc = validate(str(frontend), run_env={**env, "CLAUDE_SESSION_RULES": str(fx / "missing.sh")})
    check("validate-rules: a missing oracle turns the check OFF, loudly",
          proc.returncode == 1 and "OFF" in proc.stderr, detail(proc))
    proc = validate(str(frontend), run_env={**env, "CLAUDE_SESSION_RULES": str(silent)})
    check("validate-rules: an oracle that injects nothing is reported, not passed",
          proc.returncode == 1 and "no injection" in proc.stderr, detail(proc))
    check("validate-rules: its fixture directories are removed", not any(scratch.iterdir()),
          str(list(scratch.iterdir())))
    shutil.rmtree(fx)


def run() -> None:
    test_bash_guard()
    test_reviewer_guard()
    test_session_rules()
    test_sonar_gate()
    test_sonar_gate_script()
    test_validate_readme()
    test_validate_rules()


if __name__ == "__main__":
    run()
    for f in _failures:
        print(f"FAIL  {f}")
    total = _passes + len(_failures)
    print(f"\n{_passes}/{total} passed")
    sys.exit(1 if _failures else 0)
