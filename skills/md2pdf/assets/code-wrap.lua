-- Appended to every md2pdf build via `pandoc --lua-filter`.
--
-- Why this exists: LaTeX does NOT report an over-wide code block as an
-- overfull hbox (it only does that for prose), so a long line in a listing is
-- silently clipped at the page edge. The build exits 0 and the PDF passes every
-- automated check. fvextra makes those lines wrap with a visible continuation
-- marker instead of disappearing.
--
-- Why a Lua filter and not `--include-in-header`: pandoc's -H sets the
-- `header-includes` variable, which OVERRIDES any `header-includes` in the
-- document's YAML rather than appending to it. Using -H here silently deleted
-- document preambles (e.g. a \definecolor the frontmatter relied on). This
-- filter appends, leaving the document's own header-includes intact.
--
-- Appending last is deliberate: \fvset accumulates keys, so a document that
-- sets `fontsize=\small` keeps it, and only breaklines/breakanywhere are added.

local WRAP = [[
\usepackage{fvextra}
\fvset{breaklines=true,breakanywhere=true}
\RecustomVerbatimEnvironment{verbatim}{Verbatim}{breaklines=true,breakanywhere=true}
]]

function Meta(meta)
  -- LaTeX-only; leave every other output format untouched.
  if not (FORMAT:match('latex') or FORMAT:match('beamer')) then
    return meta
  end

  local addition = pandoc.MetaBlocks{ pandoc.RawBlock('latex', WRAP) }
  local existing = meta['header-includes']

  if existing == nil then
    meta['header-includes'] = pandoc.MetaList{ addition }
  elseif existing.t == 'MetaList' then
    existing:insert(addition)
    meta['header-includes'] = existing
  else
    meta['header-includes'] = pandoc.MetaList{ existing, addition }
  end

  return meta
end
