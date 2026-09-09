#!/bin/bash
# Stop: run the repo's own prettier over everything the turn changed.
#
# Replaces a PostToolUse-on-Edit|Write ancestor that could not see the file changes
# made through Bash, which under `defaultMode: auto` is most of them. Same opt-in as
# before — the repo needs a prettier config AND a local node_modules/.bin/prettier —
# and Java/spotless stays out, because Maven startup is too slow to sit in a turn.
#
# One prettier invocation for the whole changed set rather than one per file: node
# startup dominates the cost of formatting a handful of files.
#
# Never blocks: always exits 0. A formatter that can fail a turn is a formatter you
# start working around.

payload=$(cat)
cwd=$(printf '%s' "$payload" | /usr/bin/jq -r '.cwd // empty' 2>/dev/null)
[ -n "$cwd" ] || cwd="$PWD"

root=$(cd "$cwd" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -n "$root" ] || exit 0

has_cfg=""
for c in .prettierrc .prettierrc.json .prettierrc.js .prettierrc.cjs .prettierrc.mjs \
         .prettierrc.yml .prettierrc.yaml prettier.config.js prettier.config.cjs prettier.config.mjs; do
  if [ -f "$root/$c" ]; then has_cfg=1; break; fi
done
if [ -z "$has_cfg" ] && [ -f "$root/package.json" ]; then
  /usr/bin/jq -e '.prettier' "$root/package.json" >/dev/null 2>&1 && has_cfg=1
fi
[ -n "$has_cfg" ] || exit 0

bin="$root/node_modules/.bin/prettier"
[ -x "$bin" ] || exit 0

files=()
while IFS= read -r -d '' rec; do
  case "$rec" in
    ??\ *) f="$root/${rec#???}" ;;
    "") continue ;;
    *) f="$root/$rec" ;;
  esac
  [ -f "$f" ] || continue
  case "$f" in
    */node_modules/*|*package-lock.json|*pnpm-lock.yaml|*yarn.lock) continue ;;
    *.ts|*.tsx|*.js|*.jsx|*.mjs|*.cjs|*.css|*.scss|*.json|*.md|*.html|*.yml|*.yaml) files+=("$f") ;;
  esac
done < <(git -C "$root" status --porcelain -z --untracked-files=all 2>/dev/null)

[ "${#files[@]}" -gt 0 ] || exit 0
"$bin" --write --ignore-unknown "${files[@]}" >/dev/null 2>&1 || true
exit 0
