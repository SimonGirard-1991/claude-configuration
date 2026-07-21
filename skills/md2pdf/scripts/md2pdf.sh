#!/usr/bin/env bash
#
# md2pdf.sh — deterministic Markdown -> PDF via pandoc + LuaLaTeX.
#
# Bundled with the md2pdf skill; also the build step for learning-doc-writer
# output. Safe to run standalone:
#
#   md2pdf.sh document.md              # -> document.pdf next to the source
#   md2pdf.sh document.md out/doc.pdf  # explicit output path
#
# Why these defaults (learned failure modes, not theory):
#   - LuaLaTeX with its default Latin Modern fonts: broad unicode coverage
#     (arrows, math symbols). macOS system fonts like Helvetica Neue lack
#     common glyphs (e.g. U+2192) and render boxes — so no font override
#     here. Pass one explicitly after `--` only if you accept that tradeoff.
#   - MacTeX does not put TeX on the PATH of non-login shells; we probe the
#     standard install locations instead of requiring callers to know that.
#   - pandoc 3.9 renamed --highlight-style to --syntax-highlighting; we
#     detect which flag the installed pandoc supports.
#   - LaTeX does not warn about over-wide CODE blocks (only prose), so long
#     listing lines are silently clipped at the page edge on an exit-0 build.
#     assets/code-wrap.tex is injected on every build to force wrapping.
#   - ```mermaid blocks need mermaid-filter, else pandoc silently renders them
#     as literal source. We detect the blocks and refuse rather than degrade.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WRAP_FILTER="$SCRIPT_DIR/../assets/code-wrap.lua"

STYLE="tango"
ENGINE="lualatex"
DRY_RUN=0
NO_MERMAID=0
INPUT=""
OUTPUT=""
EXTRA=()

usage() {
  cat <<'EOF'
Usage: md2pdf.sh [options] <input.md> [output.pdf] [-- <extra pandoc args>]

Build a PDF from pandoc-flavoured Markdown with LuaLaTeX.

Options:
  -s, --style NAME    syntax-highlighting style (default: tango)
  -e, --engine NAME   PDF engine (default: lualatex)
  -n, --dry-run       print the pandoc command without running it
      --no-mermaid    build even if ```mermaid blocks cannot be rendered
                      (they come out as literal source — use knowingly)
  -h, --help          show this help

Arguments after `--` are passed to pandoc verbatim,
e.g.: md2pdf.sh doc.md -- -V mainfont="TeX Gyre Pagella"
EOF
}

die() {
  printf 'md2pdf: error: %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--style)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      STYLE="$2"; shift 2 ;;
    -e|--engine)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      ENGINE="$2"; shift 2 ;;
    -n|--dry-run)
      DRY_RUN=1; shift ;;
    --no-mermaid)
      NO_MERMAID=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    --)
      shift; EXTRA=("$@"); break ;;
    -*)
      die "unknown option: $1 (see --help)" ;;
    *)
      if [[ -z "$INPUT" ]]; then
        INPUT="$1"
      elif [[ -z "$OUTPUT" ]]; then
        OUTPUT="$1"
      else
        die "unexpected argument: $1"
      fi
      shift ;;
  esac
done

[[ -n "$INPUT" ]] || { usage >&2; exit 1; }
[[ -f "$INPUT" ]] || die "input file not found: $INPUT"
[[ -n "$OUTPUT" ]] || OUTPUT="${INPUT%.*}.pdf"
[[ "$OUTPUT" != "$INPUT" ]] || die "output would overwrite input: $INPUT"
[[ -d "$(dirname "$OUTPUT")" ]] || die "output directory does not exist: $(dirname "$OUTPUT")"

command -v pandoc >/dev/null 2>&1 ||
  die "pandoc not found — install it (macOS: brew install pandoc; Debian/Ubuntu: apt install pandoc)"

# Find the PDF engine: PATH first, then standard TeX install locations
# (MacTeX symlink dir, manual TeX Live installs). Distro TeX Live packages
# are already on PATH.
if ! command -v "$ENGINE" >/dev/null 2>&1; then
  found=0
  for dir in /Library/TeX/texbin /usr/local/texlive/*/bin/* /opt/texlive/*/bin/*; do
    if [[ -x "$dir/$ENGINE" ]]; then
      export PATH="$dir:$PATH"
      found=1
      break
    fi
  done
  [[ "$found" -eq 1 ]] ||
    die "PDF engine '$ENGINE' not found on PATH, in /Library/TeX/texbin, or under {/usr/local,/opt}/texlive/*/bin — install MacTeX (https://tug.org/mactex/) or TeX Live, or pass --engine"
fi

# pandoc >= 3.9 uses --syntax-highlighting; older releases use --highlight-style.
if pandoc --help 2>/dev/null | grep -q -- '--syntax-highlighting'; then
  highlight_flag="--syntax-highlighting=$STYLE"
else
  highlight_flag="--highlight-style=$STYLE"
fi

# ```mermaid blocks need mermaid-filter (npm). Without it pandoc does not fail
# — it renders the diagram as a literal code listing, which looks like a
# formatting bug to the reader and passes every automated check. Refuse instead.
FILTER=()
if grep -qE '^[[:space:]]*```+[[:space:]]*mermaid\b' "$INPUT"; then
  if command -v mermaid-filter >/dev/null 2>&1; then
    FILTER=(-F mermaid-filter)
    export MERMAID_FILTER_FORMAT="${MERMAID_FILTER_FORMAT:-pdf}"  # vector, for LaTeX
  elif [[ "$NO_MERMAID" -eq 1 ]]; then
    printf 'md2pdf: warning: mermaid-filter not found; diagrams will render as literal source\n' >&2
  else
    die "input has \`\`\`mermaid blocks but mermaid-filter is not installed.
Without it pandoc silently renders each diagram as a code listing.
Install it:  npm install -g mermaid-filter
Or pass --no-mermaid to build anyway, accepting unrendered diagrams."
  fi
fi

# Appended via a Lua filter, NOT --include-in-header: -H overrides the
# document's own YAML header-includes instead of appending to it.
[[ -f "$WRAP_FILTER" ]] || die "missing bundled filter: $WRAP_FILTER"

set -- pandoc "$INPUT" -o "$OUTPUT" --pdf-engine="$ENGINE" "$highlight_flag" \
  --lua-filter="$WRAP_FILTER" ${FILTER[@]+"${FILTER[@]}"} ${EXTRA[@]+"${EXTRA[@]}"}

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf '%q ' "$@"
  printf '\n'
  exit 0
fi

"$@"

# mermaid-filter drops an empty error log in the working directory; clean it up
# so it does not accumulate, but keep it if it actually captured something.
[[ -f mermaid-filter.err && ! -s mermaid-filter.err ]] && rm -f mermaid-filter.err

printf 'md2pdf: wrote %s\n' "$OUTPUT"
