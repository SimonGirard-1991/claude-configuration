#!/bin/bash
# PostToolUse on Edit|Write: run the repo's own prettier on frontend file types.
# Opt-in per repo: only runs when the repo has a prettier config AND a local
# node_modules/.bin/prettier. Java/spotless is deliberately not hooked (Maven
# startup per edit is too slow); spotless stays in the verify/CI path.
# Never blocks: always exits 0.

f=$(/usr/bin/jq -r '.tool_input.file_path // .tool_response.filePath // empty' 2>/dev/null) || exit 0
[ -n "$f" ] && [ -f "$f" ] || exit 0

case "$f" in
  */node_modules/*|*package-lock.json|*pnpm-lock.yaml|*yarn.lock) exit 0 ;;
  *.ts|*.tsx|*.js|*.jsx|*.mjs|*.cjs|*.css|*.scss|*.json|*.md|*.html|*.yml|*.yaml) ;;
  *) exit 0 ;;
esac

dir=$(dirname "$f")
root=$(cd "$dir" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)
[ -n "$root" ] || root="$dir"

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

"$bin" --write --ignore-unknown "$f" >/dev/null 2>&1 || true
exit 0
