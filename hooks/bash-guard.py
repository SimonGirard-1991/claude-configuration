#!/usr/bin/python3
"""PreToolUse guard for Bash tool calls.

Emits a permissionDecision (ask/deny) for destructive commands, commands that
print credentials, and shell access to secret-bearing files. Silent exit 0 = no
opinion, normal permission flow applies. Never emits "allow" (that would bypass
the permission system). When several rules fire, deny wins over ask.

A payload that cannot be read exits 1 with one line on stderr: non-blocking, but
visible. A guard that fails in silence is a guard that is off.

The shebang is /usr/bin/python3, not `env python3`: the env form resolves to a
pyenv shim, which fails in any repo whose .python-version names an uninstalled
interpreter, and the guard would be off in exactly the repos it protects. Keep
the code 3.9-compatible for that interpreter.

Commands are judged per segment (split on newlines and on ; && || | & and
parentheses), so a flag in one command never excuses or condemns its neighbour.

Tune patterns here; settings.json only points at this file. scripts/test_hooks.py
pins every behaviour below in both directions; change its table with the pattern.
"""
import json
import os
import re
import shlex
import sys


def decide(decision: str, reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }}))
    sys.exit(0)


try:
    cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "")
except (ValueError, AttributeError) as exc:
    print(f"bash-guard: unreadable payload ({type(exc).__name__}); no check ran for this call",
          file=sys.stderr)
    sys.exit(1)
if not isinstance(cmd, str) or not cmd:
    sys.exit(0)

verdicts = []


def flag(decision: str, reason: str) -> None:
    verdicts.append((decision, reason))


PUNCTUATION = set("();<>|&")


def segments(command: str):
    for line in command.splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:
            tokens = line.split()
        seg, skip_next = [], False
        for tok in tokens:
            if skip_next:
                skip_next = False
                continue
            if tok and set(tok) <= PUNCTUATION:
                if "<" in tok or ">" in tok:
                    if seg and seg[-1].isdigit():
                        seg.pop()
                    skip_next = True
                    continue
                if seg:
                    yield seg
                seg = []
                continue
            seg.append(tok)
        if seg:
            yield seg


# --- secrets: commands whose output is a credential -------------------------
SECRET_PRINTERS = [
    (r"\bsecurity\b[^;&|]*\b(?:find-(?:generic|internet)-password|dump-keychain|export)\b",
     "Reads secrets from the macOS Keychain."),
    (r"\bgh\s+auth\s+(?:token\b|status\b[^;&|]*(?:\s-t\b|--show-token))", "Prints the GitHub token."),
    (r"\bgcloud\s+auth\s+(?:application-default\s+)?print-(?:access|identity)-token", "Prints a GCP token."),
    (r"\baz\s+account\s+get-access-token", "Prints an Azure token."),
    (r"\baws\s+(?:configure\s+(?:get|export-credentials)|sts\s+get-session-token|ecr\s+get-login-password)",
     "Prints AWS credentials."),
    (r"\bop\s+(?:read|item\s+get)\b", "Reads a 1Password secret."),
    (r"\bpass\s+show\b", "Reads a pass secret."),
    (r"\bvault\s+(?:read|kv\s+get)\b", "Reads a Vault secret."),
    (r"\bkubectl\b[^;&|]*\bget\s+secrets?\b[^;&|]*(?:\s-o|--output)", "Prints Kubernetes secret values."),
    (r"\bgit\s+credential\s+fill\b", "Prints stored git credentials."),
    (r"\bheroku\s+auth:token\b", "Prints the Heroku token."),
]
for pattern, reason in SECRET_PRINTERS:
    if re.search(pattern, cmd):
        flag("deny", f"{reason} Secret values must never enter the transcript.")

# AUTH must not match the AUTHOR segment of GIT_AUTHOR_NAME and friends.
SECRET_VAR = (r"[A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?"
              r"|AUTH(?!OR(?:_|$|[^A-Za-z0-9_])))[A-Za-z0-9_]*")
if re.search(r"(?:^|[;&|(\n]\s*)(?:env|printenv|set|export\s+-p|declare\s+-x)\s*(?:$|[;&|)\n])", cmd):
    flag("deny", "Dumps the environment, which holds API keys.")
if re.search(rf"\bprintenv\s+{SECRET_VAR}\b", cmd) \
        or re.search(rf"\b(?:echo|printf|print)\b[^;&|\n]*\$\{{?{SECRET_VAR}", cmd):
    flag("deny", "Prints a secret-named environment variable.")

# --- secrets: shell access to secret-bearing files -------------------------
# .env / .envrc / .env.<stage>, ssh private keys, Claude credentials, PEM
# material. A template name (.env.example) is exempt per match, never for the
# whole command: `diff .env.example .env` still reads the real file.
SECRET_FILE_RE = re.compile(
    r"(?:^|[\s/=('\"<>`])(?P<env>\.env(?:rc)?(?:\.[\w.-]+)?)(?=$|[\s;|&)'\"<>`])"
    r"|id_rsa|id_ed25519|id_ecdsa"
    r"|\.credentials\.json"
    r"|[\w.-]+\.(?:pem|p12|pfx)\b"
    r"|\.ssh/|\.gnupg/|\.aws/credentials|\.netrc\b|\.git-credentials"
    r"|\.npmrc\b|\.pypirc\b|\.docker/config\.json|\.kube/config"
    r"|gh/hosts\.yml|\.config/gcloud|application_default_credentials\.json"
)
TEMPLATE_ENV_RE = re.compile(r"\.env\.(?:example|sample|template|dist|test)")
for m in SECRET_FILE_RE.finditer(cmd):
    if m.group("env") and TEMPLATE_ENV_RE.fullmatch(m.group("env")):
        continue
    flag("ask", "Command references a potential secrets file (.env/keys/credentials). "
                "Approve only if no secret value can end up in the transcript.")
    break

# --- git: history-rewriting / data-destroying ------------------------------
GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}


def git_subcommand(seg):
    for i, tok in enumerate(seg):
        if tok != "git" and not tok.endswith("/git"):
            continue
        j = i + 1
        while j < len(seg) and seg[j].startswith("-"):
            j += 2 if seg[j] in GIT_OPTIONS_WITH_VALUE else 1
        return (seg[j], seg[j + 1:]) if j < len(seg) else (None, [])
    return None, []


def short_flags(args):
    return "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))


def push_risk(args):
    if "--dry-run" in args or "n" in short_flags(args):
        return None
    lease = any(a.startswith("--force-with-lease") for a in args)
    for a in args:
        if a in ("--mirror", "--prune", "--delete") or a.startswith(":"):
            return "Deleting push removes remote branches or tags."
        if a.startswith("--"):
            if a == "--force" and not lease:
                return "Force push rewrites remote history. Prefer --force-with-lease."
            continue
        if a.startswith("-"):
            if "d" in a[1:]:
                return "Deleting push removes remote branches or tags."
            if "f" in a[1:] and not lease:
                return "Force push rewrites remote history. Prefer --force-with-lease."
            continue
        if a.startswith("+") and not lease:
            return "A '+' refspec force-pushes that ref. Prefer --force-with-lease."
    return None


for seg in segments(cmd):
    sub, args = git_subcommand(seg)
    if sub == "push":
        risk = push_risk(args)
        if risk:
            flag("ask", risk)
    elif sub == "reset" and "--hard" in args:
        flag("ask", "git reset --hard discards uncommitted work.")
    elif sub == "clean":
        dry = "--dry-run" in args or "n" in short_flags(args)
        if not dry and ("--force" in args or re.search(r"[fdxX]", short_flags(args))):
            flag("ask", "git clean deletes untracked files.")

# --- rm: catastrophic scope -------------------------------------------------
HOME = os.path.expanduser("~")
for seg in segments(cmd):
    for i, tok in enumerate(seg):
        if tok != "rm" and not tok.endswith("/rm"):
            continue
        args = seg[i + 1:]
        flags = [a for a in args if a.startswith("-")]
        targets = [a for a in args if not a.startswith("-")]
        if "--no-preserve-root" in flags:
            flag("deny", "rm --no-preserve-root is blocked.")
        recursive = "--recursive" in flags or any(
            re.match(r"-[a-zA-Z]*[rR]", f) for f in flags if not f.startswith("--"))
        if not recursive:
            continue
        for tgt in targets:
            norm = tgt.replace("${HOME}", "~").replace("$HOME", "~")
            expanded = os.path.expanduser(norm)
            stripped = expanded.rstrip("/*") or "/"
            here = tgt.replace("${PWD}", "$PWD").rstrip("/*")
            if (tgt in ("/", "/*", "*", "~", "~/", "~/*", "..", "../")
                    or stripped == HOME
                    or stripped == "/"
                    or expanded.startswith("..")
                    or re.match(r"^/[^/]+$", stripped)):
                flag("deny", f"rm -r targeting '{tgt}' is blocked (home, root, or top-level system path).")
            elif here in (".", "$PWD"):
                flag("ask", f"rm -r targeting '{tgt}' deletes the current directory.")
            elif os.path.basename(here) == ".git":
                flag("ask", f"rm -r targeting '{tgt}' deletes the repository's history.")

if verdicts:
    denials = [reason for decision, reason in verdicts if decision == "deny"]
    if denials:
        decide("deny", denials[0])
    decide("ask", verdicts[0][1])
sys.exit(0)
