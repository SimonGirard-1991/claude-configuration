#!/usr/bin/python3
"""PreToolUse guard for the code-reviewer subagent, wired from its frontmatter.

The reviewer is read-only on the repo by contract, but `memory: user` auto-enables
Write and Edit, so until this hook the prompt alone held that line. Now:

- Edit/Write land only in the reviewer's memory directory or a scratch location
  ($TMPDIR, /private/tmp, the session scratchpad). Anything else, including a
  missing path, is denied with the reason.
- Bash: git is allowlisted rather than blocklisted, so an alias or an unusual write
  verb is denied by default. In-place editors, interactive editors, eval,
  `sh -c`, file-mutating commands and redirects or tee into anything but scratch
  are denied, and so is gh beyond read-only views. Test runners and builds pass:
  their artifacts are untracked, and the prompt already demands a clean
  `git status` afterwards.

This catches accidents, not a determined adversary: a script that opens files
itself is out of its sight. A pass is silence (the normal permission flow
applies); it never emits "allow". It fails closed: a payload it cannot read is
denied. /usr/bin/python3 for the reason bash-guard.py gives. scripts/test_hooks.py
pins the table.
"""
import json
import os
import re
import shlex
import sys


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"code-reviewer is read-only on the repo: {reason}",
    }}))
    sys.exit(0)


try:
    payload = json.load(sys.stdin)
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
except (ValueError, AttributeError) as exc:
    deny(f"reviewer-guard could not read the hook payload ({type(exc).__name__}).")

MEMORY_DIR = os.path.realpath(os.path.expanduser("~/.claude/agent-memory/code-reviewer"))
SCRATCH = [os.path.realpath(p) for p in (
    os.environ.get("TMPDIR") or "/private/tmp",
    "/private/tmp",
    payload.get("scratchpad_dir") or "/private/tmp",
)]
WHERE = f"scratch files go in $TMPDIR or /private/tmp, memory in {MEMORY_DIR}"


def resolve(path: str) -> str:
    return os.path.realpath(os.path.expandvars(os.path.expanduser(path)))


def inside(path: str, roots) -> bool:
    return any(os.path.commonpath([path, root]) == root for root in roots)


def writable(path: str, memory_ok: bool = False) -> bool:
    if path in ("/dev/null", "/dev/stdout", "/dev/stderr"):
        return True
    real = resolve(path)
    return inside(real, SCRATCH) or (memory_ok and inside(real, [MEMORY_DIR]))


if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not target:
        deny(f"{tool} without a file path.")
    if not writable(target, memory_ok=True):
        deny(f"{tool} of {target} is outside the allowed locations ({WHERE}).")
    sys.exit(0)

if tool != "Bash":
    sys.exit(0)

command = tool_input.get("command") or ""
PUNCTUATION = set("();<>|&")


def segments(text: str):
    for line in text.splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:
            tokens = line.split()
        words, redirects, pending = [], [], None
        for tok in tokens:
            if pending is not None:
                redirects.append((pending, tok))
                pending = None
                continue
            if tok and set(tok) <= PUNCTUATION:
                if "<" in tok or ">" in tok:
                    if words and words[-1].isdigit():
                        words.pop()
                    pending = tok
                    continue
                if words or redirects:
                    yield words, redirects
                words, redirects = [], []
                continue
            words.append(tok)
        if words or redirects:
            yield words, redirects


def name(word: str) -> str:
    return word.rsplit("/", 1)[-1]


def positionals(args):
    return [a for a in args if not a.startswith("-")]


WRAPPERS = {"env", "command", "builtin", "exec", "sudo", "nice", "nohup", "time",
            "xargs", "timeout", "caffeinate"}


def command_positions(words):
    i = 0
    while i < len(words):
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[i]):
            i += 1
            continue
        yield i
        wrapper = name(words[i])
        if wrapper not in WRAPPERS:
            return
        i += 1
        while i < len(words) and (words[i].startswith("-")
                                  or (wrapper == "timeout" and words[i][:1].isdigit())):
            i += 1


GIT_READ_ONLY = {
    "status", "diff", "log", "show", "blame", "annotate", "grep", "ls-files", "ls-tree",
    "cat-file", "rev-parse", "rev-list", "merge-base", "describe", "shortlog",
    "for-each-ref", "show-ref", "name-rev", "range-diff", "check-ignore", "count-objects",
    "whatchanged", "var", "help", "version",
}
GIT_GLOBAL_FLAGS = {"--no-pager", "-P", "--paginate", "-p", "--no-optional-locks",
                    "--literal-pathspecs", "--no-replace-objects", "--bare"}
LISTING = {"-l", "--list", "--contains", "--no-contains", "--merged", "--no-merged",
           "--points-at", "-a", "--all", "-r", "--remotes", "-v", "-vv", "--show-current"}
BRANCH_WRITES = {"-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy",
                 "-u", "--set-upstream-to", "--unset-upstream", "-f", "--force",
                 "--edit-description", "-t", "--track"}
TAG_WRITES = {"-d", "--delete", "-a", "--annotate", "-s", "--sign", "-u", "-f",
              "--force", "-m", "--message", "-F", "--file", "-e", "--edit"}
CONFIG_READS = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l"}
CONFIG_WRITES = {"--unset", "--unset-all", "--add", "--replace-all", "--rename-section",
                 "--remove-section", "-e", "--edit"}


def git_problem(args):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        opt = args[i]
        if opt == "-c" or opt.startswith(("--config-env", "--exec-path")):
            return f"git {opt} can make git run an arbitrary program"
        if opt in ("-C", "--git-dir", "--work-tree", "--namespace"):
            i += 2
            continue
        if opt.startswith(("--git-dir=", "--work-tree=", "--namespace=")) or opt in GIT_GLOBAL_FLAGS:
            i += 1
            continue
        if opt in ("--version", "--help", "-h"):
            return None
        return f"git {opt} is not a recognised read-only option"
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1:]
    flags = set(rest)
    if sub in GIT_READ_ONLY:
        if sub == "diff" and any(a.startswith("--output") for a in rest):
            return "git diff --output writes a file"
        return None
    if sub == "reflog" and positionals(rest)[:1] not in (["expire"], ["delete"]):
        return None
    if sub == "stash" and rest[:1] in (["list"], ["show"]):
        return None
    if sub == "branch" and not flags & BRANCH_WRITES and (not positionals(rest) or flags & LISTING):
        return None
    if sub == "tag" and not flags & TAG_WRITES and (not positionals(rest) or flags & (LISTING | {"-n"})):
        return None
    if sub == "config" and not flags & CONFIG_WRITES and (
            flags & CONFIG_READS or rest[:1] in (["get"], ["list"]) or len(positionals(rest)) == 1):
        return None
    if sub == "remote" and (not rest or rest[0] in ("-v", "--verbose", "show", "get-url")):
        return None
    if sub in ("worktree", "submodule") and rest[:1] in (["list"], ["status"]):
        return None
    return f"git {sub} is not on the read-only allowlist"


GH_READ_ONLY = {"pr": {"view", "diff", "list", "checks", "status"},
                "issue": {"view", "list", "status"},
                "run": {"view", "list"},
                "repo": {"view"}}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
EDITORS = {"vi", "vim", "nvim", "nano", "emacs", "ed", "ex"}
DESTINATION_LAST = {"cp", "mv", "install", "ln", "rsync"}
EVERY_OPERAND = {"rm", "rmdir", "touch", "mkdir", "truncate", "chmod", "chown", "unlink"}


def gh_words(args):
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in ("-R", "--repo"):
            skip = True
        elif not a.startswith("-"):
            out.append(a)
    return out


def segment_problem(words, redirects):
    for op, target in redirects:
        if ">" in op and not (target.isdigit() or target == "-") and not writable(target):
            return f"redirect into {target} ({WHERE})"
    for i in command_positions(words):
        cmd, args = name(words[i]), words[i + 1:]
        if cmd == "git":
            problem = git_problem(args)
            if problem:
                return problem
        elif cmd == "sed" and any(re.match(r"^-[a-zA-Z]*i", a) or a.startswith("--in-place") for a in args):
            return "sed -i edits files in place"
        elif cmd == "perl" and any(re.match(r"^-[pnlaws0-9]*i", a) for a in args):
            return "perl -i edits files in place"
        elif cmd in EDITORS:
            return f"{cmd} is an editor"
        elif cmd == "eval":
            return "eval cannot be inspected"
        elif cmd in SHELLS and args and re.match(r"^-[a-zA-Z]*c", args[0]):
            return f"{cmd} -c cannot be inspected"
        elif cmd == "tee":
            bad = [t for t in positionals(args) if not writable(t)]
            if bad:
                return f"tee into {bad[0]} ({WHERE})"
        elif cmd == "gh" and gh_words(args):
            group, action = (gh_words(args) + [""])[:2]
            if action not in GH_READ_ONLY.get(group, set()):
                return f"gh {group} {action} is not a read-only view".rstrip()
        elif cmd in DESTINATION_LAST and positionals(args):
            if not writable(positionals(args)[-1]):
                return f"{cmd} into {positionals(args)[-1]} ({WHERE})"
        elif cmd in EVERY_OPERAND:
            operands = positionals(args)[1:] if cmd in ("chmod", "chown") else positionals(args)
            bad = [t for t in operands if not writable(t)]
            if bad:
                return f"{cmd} {bad[0]} ({WHERE})"
    return None


for words, redirects in segments(command):
    problem = segment_problem(words, redirects)
    if problem:
        deny(f"{problem}.")
sys.exit(0)
