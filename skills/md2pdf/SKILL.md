---
name: md2pdf
description: >-
  Build a PDF from pandoc-flavoured Markdown via the bundled deterministic
  script (pandoc + LuaLaTeX). Use whenever the user asks to convert a Markdown
  doc to PDF, "build the PDF", "run pandoc", or wants a learning-doc-writer
  output as a PDF. Handles TeX-not-on-PATH (MacTeX), pandoc flag renames, and
  unicode-safe font defaults so you never hand-roll a pandoc command.
---

# Markdown -> PDF builder

One command, no improvisation:

```bash
~/.claude/skills/md2pdf/scripts/md2pdf.sh <input.md> [output.pdf]
```

The script is the single source of truth for the build. It:

- finds the PDF engine even when TeX is not on the Bash tool's PATH (MacTeX
  installs to `/Library/TeX/texbin`, which non-login shells don't see);
- picks `--syntax-highlighting` (pandoc >= 3.9) or `--highlight-style` (older)
  to match the installed pandoc;
- keeps LuaLaTeX with its default Latin Modern fonts — broad unicode coverage
  (arrows, math), where macOS system fonts render missing-glyph boxes;
- appends `assets/code-wrap.lua` (`fvextra`) on every build so long code lines
  wrap instead of being silently clipped at the page edge;
- renders ` ```mermaid ` blocks to vector diagrams when the source contains
  them, via `mermaid-filter`;
- fails with an actionable install hint when pandoc or TeX is missing — relay
  that hint to the user instead of working around it.

Useful flags: `--dry-run` prints the exact pandoc command without running it;
`-s/--style` changes the highlight style; anything after `--` goes to pandoc
verbatim (e.g. `-- -V mainfont="TeX Gyre Pagella"` — only override fonts if the
user explicitly accepts the glyph-coverage tradeoff).

## Source-document requirements

The input must be pandoc-ready (learning-doc-writer output already is):

- `linkcolor` in the YAML frontmatter must be a plain colour NAME — either a
  named LaTeX colour or one defined in `header-includes` with
  `\definecolor{doclink}{HTML}{1F6FEB}`. An `[HTML]{RRGGBB}` literal or `#hex`
  string gets LaTeX-escaped by pandoc and reaches `hyperref` mangled. The build
  still succeeds — the links just come out the wrong colour, silently, which is
  why this one goes unnoticed. Check the rendered links, not the exit code.
- Fenced code blocks need language tags to get colours.
- No smart quotes pasted in from web copy (a frequent silent breakage).

## Diagrams

Use ` ```mermaid ` blocks — `classDiagram` (UML, with `<<interface>>` stereotypes
and `Type~R~` generics), `sequenceDiagram`, `stateDiagram-v2`, `flowchart`. The
script renders them as vector PDF via `mermaid-filter` (npm), the same pipeline
as `~/Documents/WorkTemplate/SystemDesign/build-pdfs.sh`. Reserve ASCII art for
what Mermaid renders worse: memory layouts, wire formats, column-aligned tables.

If the source has mermaid blocks and `mermaid-filter` is missing, the script
**refuses to build**. That is deliberate: pandoc's own behaviour is to render
the diagram as literal source, which passes every automated check and looks like
a formatting bug to the reader. Install it (`npm install -g mermaid-filter`) or
pass `--no-mermaid` to accept unrendered diagrams knowingly.

## The failures here are silent — verify by looking

This pipeline's characteristic bugs all produce an exit-0 build and a plausible
PDF. **After any build of a code- or diagram-heavy document, rasterise a page
and actually look at it:**

```bash
pdftoppm -png -r 110 -f 7 -l 7 doc.pdf out   # then read out-07.png
```

Known silent modes, and who guards them now:

| Symptom | Cause | Guard |
|---|---|---|
| Code clipped at page edge | LaTeX warns on over-wide prose, never on code blocks | script appends `fvextra` |
| Diagram appears as source text | `mermaid-filter` absent | script refuses to build |
| Links in the wrong colour | escaped `linkcolor` (see above) | nothing — check by eye |
| Document's `header-includes` vanishes | `pandoc -H` **overrides** YAML `header-includes` rather than appending | script uses `--lua-filter`, never `-H` |

That last row is why the wrapping ships as a Lua filter that appends to
`header-includes`. Adding it with `--include-in-header` deleted the document's
own preamble — caught only because a `\definecolor` disappeared and the build
failed loudly. A document without a custom colour would have lost its preamble
silently. **Never add preamble content to this pipeline with `-H`.**

## Troubleshooting

- **`lualatex` not found** even though the script probed the standard
  locations: TeX is not installed — suggest MacTeX (https://tug.org/mactex/)
  on macOS or TeX Live elsewhere.
- **A unicode glyph renders as a box**: fix the engine/font, don't strip the
  glyph from the prose. Latin Modern (the default) covers arrows and math;
  a user-requested font override is usually the culprit.
- **Links render in the wrong colour** (build exited 0): `linkcolor` is an
  escaped `[HTML]{...}` literal or `#hex` string — see the rule above. This is
  a silent failure, so it will not show up in the build output.
- **Build fails on the frontmatter**: suspect malformed YAML or a
  `header-includes` LaTeX command that does not exist — not `linkcolor`,
  which fails silently rather than loudly.
