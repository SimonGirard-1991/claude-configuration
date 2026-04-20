---
name: macOS Docker Desktop diagnostics — socket and cred helper PATH
description: When Docker commands fail on macOS with cred-helper or socket errors, do not conclude the daemon is off. Check `docker context ls` and `/Applications/Docker.app/Contents/Resources/bin` PATH first.
type: feedback
---

On macOS, a non-interactive Bash subshell does NOT inherit Docker Desktop's
shell-integration PATH. This produces two misleading error modes that look
like "daemon is down" but are really "missing environment":

1. `error getting credentials - err: exec: "docker-credential-desktop":
   executable file not found in $PATH` — the helper binary exists at
   `/Applications/Docker.app/Contents/Resources/bin/docker-credential-desktop`
   but that directory is not on PATH in the subshell.
2. `dial unix /var/run/docker.sock: connect: no such file or directory` — the
   socket path is wrong. Recent Docker Desktop versions use a user-space
   socket at `~/.docker/run/docker.sock` via the `desktop-linux` context,
   not the classic `/var/run/docker.sock`.

**Why:** I spent a round trip with the user telling them "Docker isn't running"
when in fact it was running fine and I just didn't have the PATH or context
right in the subshell I was executing in.

**How to apply — diagnostic order before concluding the daemon is off:**

1. `ps -ef | grep -iE 'docker|colima|orbstack|rancher' | grep -v grep` —
   are the Docker Desktop processes actually running?
2. `docker context ls` — which context is active, where's the endpoint?
3. `ls -la ~/.docker/run/docker.sock` — does the user-space socket exist?
4. `ls /Applications/Docker.app/Contents/Resources/bin/` — is the cred helper
   installed?

If 1–4 all succeed and `docker` commands still fail, the fix is almost
always PATH-prepending the Docker Desktop bin dir for the command:

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
```

Not a config change, not a service restart — just PATH.

**When this does NOT apply:**

- Linux hosts — sockets are at `/var/run/docker.sock` or `/run/user/<uid>/docker.sock`
  (rootless), no credential-helper PATH gymnastics.
- Users running Colima, OrbStack, or Rancher Desktop instead of Docker Desktop —
  their socket paths and helper binaries live elsewhere.
