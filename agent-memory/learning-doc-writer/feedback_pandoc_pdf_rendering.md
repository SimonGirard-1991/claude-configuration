---
name: Pandoc PDF rendering pitfalls on the user's macOS setup
description: Concrete fixes for the recurring pandoc/lualatex breakages on this user's system; supersedes the default invocation in the system prompt for any doc containing unicode.
type: feedback
---

The default pandoc invocation suggested by the system prompt
(`--highlight-style=tango`, `--pdf-engine=xelatex`,
`-V mainfont="Helvetica Neue"`, `-V monofont="Menlo"`) breaks in several
distinct ways on this user's macOS setup. Capture these once; do not
rediscover them per conversation.

**Why:** the user works on macOS with TeX Live 2026 installed at
`/Library/TeX/texbin`, and pandoc 3.9.0.2. Helvetica Neue on this system
is the AAT (`mapping=tex-text`) version, which lacks several common
unicode glyphs (notably U+2192 right arrow). Pandoc 3.9 deprecated
`--highlight-style` and tightened YAML escaping for `linkcolor`. The
system PATH used by Claude Code's Bash tool does not include the TeX
directory.

**How to apply.** Use this invocation as the default for any doc the
agent renders, and only deviate when the doc is pure ASCII:

```bash
PATH="/Library/TeX/texbin:$PATH" pandoc <name>.md -o <name>.pdf \
  --pdf-engine=lualatex \
  --syntax-highlighting=tango
```

And use this YAML frontmatter pattern as the safe default for any doc
with colored links and unicode math glyphs:

```yaml
colorlinks: true
linkcolor: githublue
header-includes:
  - \definecolor{githublue}{HTML}{1F6FEB}
  - \usepackage{newunicodechar}
  - \newunicodechar{≥}{\ensuremath{\geq}}
  - \newunicodechar{≤}{\ensuremath{\leq}}
```

Specifically:

1. **PATH augmentation is required.** The shell launched by the Bash
   tool does not have `/Library/TeX/texbin` on PATH; `which lualatex`
   returns "not found" without it. Always prepend the path.

2. **Prefer lualatex over xelatex when the doc contains any unicode
   beyond Latin-1.** Both engines are unicode-aware, but the *font*
   matters: xelatex with Helvetica Neue surfaces "Missing character:
   There is no -> (U+2192)" and renders boxes. lualatex without an
   explicit `mainfont` falls back to Latin Modern, which has broad
   unicode coverage including U+2192. Drop the `-V mainfont` and
   `-V monofont` overrides from the system prompt's default invocation
   when using lualatex.

3. **Use `--syntax-highlighting=<style>`, not `--highlight-style=<style>`.**
   The latter is deprecated in pandoc 3.9+ and prints a warning on every
   invocation. The accepted values are the same (`tango`, `pygments`,
   `kate`, etc.).

4. **Pandoc 3.9+ TeX-escapes `linkcolor` values, breaking the `[HTML]{...}`
   form.** What used to work — `linkcolor: "[HTML]{1F6FEB}"` — now produces
   `Package xcolor Error: Undefined color '{[}HTML{]}\{1F6FEB\}'`, because
   the brackets and braces are escaped instead of being passed through as
   raw LaTeX. The fix: define the color in `header-includes` and reference
   it by name. Do NOT use hex with `#` prefix, that breaks differently. Do
   use a named color (`linkcolor: blue`) if you do not care about the
   exact shade.

5. **Latin Modern lacks `≥` (U+2265) and `≤` (U+2264).** It does have
   `→` (U+2192), `±` (U+00B1), `×` (U+00D7) and most others. When the
   prose meaningfully uses `≥` / `≤`, add a `newunicodechar` mapping in
   `header-includes` rather than substituting `>=` / `<=` in source.
   Pattern: `\newunicodechar{≥}{\ensuremath{\geq}}`.

6. **Doc style: keep avoiding decorative unicode in source where ASCII
   suffices** (the system prompt already says this), but when the
   user's prose meaningfully uses arrows or other glyphs, lualatex +
   default font + a `newunicodechar` mapping for the rare missing glyph
   is the path that actually renders them. Do not silently substitute
   ASCII without telling the user.
