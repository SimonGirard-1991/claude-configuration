#!/usr/bin/env python3
"""PreToolUse guard for Bash tool calls.

Emits a permissionDecision (ask/deny) for destructive commands, commands that
print credentials, and shell access to secret-bearing files. Silent exit 0 = no opinion, normal permission
flow applies. Never emits "allow" (that would bypass the permission system).
Fails open: any parse error exits 0.

Tune patterns here; settings.json only points at this file.
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
except Exception:
    sys.exit(0)
if not isinstance(cmd, str) or not cmd:
    sys.exit(0)

# --- secrets: shell access to secret-bearing files -------------------------
# .env / .envrc / .env.<stage> (but not .env.example-style templates),
# ssh private keys, Claude credentials, PEM material.
SECRET_FILE_RE = re.compile(
    r"(?:^|[\s/=('\"])\.env(?:rc)?(?:\.[\w.-]+)?(?=$|[\s;|&)'\"])"
    r"|id_rsa|id_ed25519|id_ecdsa"
    r"|\.credentials\.json"
    r"|[\w.-]+\.(?:pem|p12|pfx)\b"
    r"|\.ssh/|\.gnupg/|\.aws/credentials|\.netrc\b|\.git-credentials"
    r"|\.npmrc\b|\.pypirc\b|\.docker/config\.json|\.kube/config"
    r"|gh/hosts\.yml|\.config/gcloud|application_default_credentials\.json"
)
TEMPLATE_ENV_RE = re.compile(r"\.env\.(?:example|sample|template|dist|test)\b")

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
        decide("deny", f"{reason} Secret values must never enter the transcript.")

SECRET_VAR = r"[A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?|AUTH)[A-Za-z0-9_]*"
if re.search(r"(?:^|[;&|(]\s*)(?:env|printenv|set|export\s+-p|declare\s+-x)\s*(?:$|[;&|)])", cmd):
    decide("deny", "Dumps the environment, which holds API keys.")
if re.search(rf"\bprintenv\s+{SECRET_VAR}\b", cmd) \
        or re.search(rf"\b(?:echo|printf|print)\b[^;&|]*\$\{{?{SECRET_VAR}", cmd):
    decide("deny", "Prints a secret-named environment variable.")

if SECRET_FILE_RE.search(cmd) and not TEMPLATE_ENV_RE.search(cmd):
    decide("ask", "Command references a potential secrets file (.env/keys/credentials). Approve only if no secret value can end up in the transcript.")

# --- git: history-rewriting / data-destroying ------------------------------
if re.search(r"\bgit\b", cmd):
    if re.search(r"\bpush\b", cmd):
        if not re.search(r"--force-with-lease|--force-if-includes", cmd):
            if re.search(r"--force\b|(?:^|\s)-f\b|--delete\b|(?:^|\s)-d\b|\s\+\S+:", cmd):
                decide("ask", "Force/delete push rewrites or removes remote history. Prefer --force-with-lease.")
    if re.search(r"\breset\b", cmd) and "--hard" in cmd:
        decide("ask", "git reset --hard discards uncommitted work.")
    if re.search(r"\bclean\b", cmd) and re.search(r"(?:^|\s)-[a-zA-Z]*[fdxX]", cmd) \
            and not re.search(r"(?:^|\s)-[a-zA-Z]*n|--dry-run", cmd):
        decide("ask", "git clean deletes untracked files.")

# --- rm: catastrophic scope -------------------------------------------------
try:
    toks = shlex.split(cmd)
except ValueError:
    toks = cmd.split()
SEPS = {";", "&&", "||", "|", "&"}
HOME = os.path.expanduser("~")
for i, tok in enumerate(toks):
    if tok != "rm" and not tok.endswith("/rm"):
        continue
    args = []
    for nxt in toks[i + 1:]:
        if nxt in SEPS:
            break
        args.append(nxt)
    flags = [a for a in args if a.startswith("-")]
    targets = [a for a in args if not a.startswith("-")]
    if "--no-preserve-root" in flags:
        decide("deny", "rm --no-preserve-root is blocked.")
    recursive = "--recursive" in flags or any(
        re.match(r"-[a-zA-Z]*[rR]", f) for f in flags if not f.startswith("--"))
    if not recursive:
        continue
    for tgt in targets:
        norm = tgt.replace("$HOME", "~").replace("${HOME}", "~")
        expanded = os.path.expanduser(norm)
        stripped = expanded.rstrip("/*") or "/"
        if (tgt in ("/", "/*", "*", "~", "~/", "~/*", "..", "../")
                or stripped == HOME
                or stripped == "/"
                or expanded.startswith("..")
                or re.match(r"^/[^/]+$", stripped)):
            decide("deny", f"rm -r targeting '{tgt}' is blocked (home, root, or top-level system path).")

sys.exit(0)
