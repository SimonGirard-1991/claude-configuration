#!/usr/bin/env python3
"""Lint the skill tree for the defect classes that hand-editing keeps reintroducing.

Two tiers, and the split is the whole design:

  ERROR  — mechanically certain. A dangling route, a name that disagrees with its
           directory, a heading that skips a level. These have one right answer,
           so blocking an edit on them is fair.
  WARN   — judgement-shaped. "This backticked token looks like it was meant to be
           a skill." "This sentence sounds like a sufficiency claim." Prose will
           always find new ways to trip these, so they must never block.

An earlier version blocked on the second tier and produced false positives on
ordinary prose — a backticked table name near the word "skill", a mention of
README.md, a link carrying a #fragment. A gate that fires on correct content
teaches you to work around the gate. Keep new checks in the tier they belong to.

The checks are covered by scripts/test_lint_skills.py. A check without a
fixture test is a check that may silently match nothing; add the test first.

Usage:
    lint_skills.py [--skills-dir DIR] [--agents-dir DIR] [--scope PATH]
                   [--transient-ok] [--quiet]

Exit status: 0 clean, 3 findings, 2 bad invocation. An uncaught exception exits
1 — callers must not confuse that with findings.
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SKILLS = Path.home() / ".claude" / "skills"
DEFAULT_AGENTS = Path.home() / ".claude" / "agents"

EXIT_CLEAN, EXIT_BAD_INVOCATION, EXIT_FINDINGS = 0, 2, 3

# Skills that are real and invocable but do not live in ~/.claude/skills:
# harness built-ins and bundled plugins. Routing to one of these is correct, so
# it must not be reported as a nonexistent skill.
BUILTIN_SKILLS = {
    "artifact-capabilities", "artifact-design", "artifact-diagramming",
    "claude-api", "code-review", "dataviz", "fewer-permission-prompts",
    "frontend-design", "init", "keybindings-help", "loop", "run", "schedule",
    "security-review", "simplify", "update-config",
}

# Documents that legitimately exist outside a references/ directory. Naming one
# from inside references/ is a normal cross-reference, not a dangling sibling.
ROOT_DOCS = {"SKILL.md", "README.md", "CLAUDE.md", "AGENTS.md", "RTK.md", "MEMORY.md"}

# Spine sections a reference header may claim SKILL.md carries.
SPINE_CLAIMS = {
    "when to use": r"^#{2,6} .*when to use",
    "core principles": r"^#{2,6} .*core principle",
    "review checklist": r"^#{2,6} .*checklist",
    "refusals": r"^#{2,6} .*(anti-patterns to refuse|refuse|refusal)",
    "reference map": r"^#{2,6} .*reference map",
}

# A spine that claims to be sufficient has been wrong every time it was written.
SUFFICIENCY_STRONG = re.compile(
    r"without (?:opening|loading|reading|consulting) (?:a|an|any|the)?\s*reference"
    r"|whole decision spine"
    r"|sufficient on its own"
    r"|everything you need is here",
    re.I)
SUFFICIENCY_WEAK = re.compile(r"self-contained|stands? alone", re.I)
SUFFICIENCY_CONTEXT = re.compile(r"reference|spine|SKILL\.md|checklist|review", re.I)

POSITIONAL = re.compile(
    r"(section|checklist|list|table|map|stance|rule|principle)s?\b[^.]{0,30}\b(above|below)\b"
    r"|\b(above|below)\b[^.]{0,30}\b(section|checklist|list|table)s?\b", re.I)

# Contexts in which a backticked token is being presented as a skill name.
SKILL_EXPLICIT = [
    r"\bload(?:ing|s|ed)?\b[^.]{{0,40}}`{name}`",
    r"\binvoke[a-z]*\b[^.]{{0,40}}`{name}`",
    r"\bskills?\b[^.]{{0,40}}`{name}`",
    r"`{name}`[^.]{{0,20}}\bskill\b",
]
# An arrow just means "leads to" — `pytest`, `shared`, `bats-core` are all
# legitimate arrow targets.
SKILL_ARROW = r"(?:→|->)\s*\**`{name}`"
TYPO_CUTOFF = 0.82
# Backticked tokens that are plainly not skills.
NOT_A_SKILL = re.compile(r"\.|/|-v\d+$|^\d")

FENCE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})(.*)$")
# `references/x.md`, [text](references/x.md), [text](./references/x.md#anchor)
ROUTE_BACKTICK = re.compile(r"`(?:\./)?references/([\w.-]+\.md)(?:#[\w-]+)?`")
ROUTE_LINK = re.compile(r"\]\(\s*(?:\./)?references/([\w.-]+\.md)(?:#[\w-]+)?\s*\)")


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int | str
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.code}] {self.message}"


class Report:
    def __init__(self, transient_ok: bool = False) -> None:
        self.errors: list[Finding] = []
        self.warnings: list[Finding] = []
        # MAP_MISSING/MAP_UNROUTED describe a half-finished two-file edit as
        # readily as real drift. Interactive callers pass transient_ok so an
        # in-progress refactor is reported without blocking the next keystroke.
        self.transient_ok = transient_ok

    def err(self, path: Path, line: int | str, code: str, msg: str) -> None:
        if self.transient_ok and code in ("MAP_MISSING", "MAP_UNROUTED"):
            self.warnings.append(Finding(path, line, code, msg))
            return
        self.errors.append(Finding(path, line, code, msg))

    def warn(self, path: Path, line: int | str, code: str, msg: str) -> None:
        self.warnings.append(Finding(path, line, code, msg))


def read(path: Path, rep: Report) -> str | None:
    """Read a file, reporting rather than raising. One bad byte must not end the run."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        rep.err(path, 1, "UNREADABLE", f"not valid UTF-8 ({e.reason}); cannot be linted")
    except OSError as e:
        rep.err(path, 1, "UNREADABLE", f"cannot be read: {e.strerror}")
    return None


def strip_frontmatter(lines: list[str]) -> int:
    """Return the index of the first body line, skipping YAML frontmatter."""
    if not lines or lines[0].strip() != "---":
        return 0
    for j in range(1, len(lines)):
        if lines[j].strip() == "---":
            return j + 1
    return 0


def scan_fences(lines: list[str]) -> tuple[list[tuple[int, str]], int | None]:
    """Split lines into those outside fenced blocks, plus any unterminated fence.

    Tracks the opening marker so a nested ```java inside a ````md block does not
    close it, and so an info string (```java) is never mistaken for a closer.
    Returns (outside, opened_at) where opened_at is the 1-based line of a fence
    that is never closed.
    """
    outside: list[tuple[int, str]] = []
    marker: str | None = None
    opened_at: int | None = None
    for i, line in enumerate(lines, 1):
        m = FENCE.match(line)
        if m:
            found, info = m.group(2), m.group(3).strip()
            if marker is None:
                marker, opened_at = found, i
            elif found[0] == marker[0] and len(found) >= len(marker) and not info:
                marker, opened_at = None, None
            continue
        if marker is None:
            outside.append((i, line))
    return outside, opened_at


def outside_fences(lines: list[str]):
    """Yield (1-based lineno, text) for lines outside fenced blocks."""
    yield from scan_fences(lines)[0]


# ── checks ───────────────────────────────────────────────────────────────

def check_fences(path: Path, lines: list[str], rep: Report) -> bool:
    """An unterminated fence hides the rest of the file from every other check,
    which surfaces as a cascade of phantom findings. Name the real defect and
    let the caller suppress the checks that would cascade off it."""
    opened_at = scan_fences(lines)[1]
    if opened_at is None:
        return False
    rep.err(path, opened_at, "UNTERMINATED_FENCE",
            "code fence opened here is never closed; everything below it is "
            "invisible to the linter")
    return True


def check_reference_paths(ref: Path, body: str, siblings: set[str], rep: Report) -> None:
    """Inside references/, `references/x.md` resolves to references/references/x.md,
    and a bare sibling name should actually name a sibling."""
    for i, line in outside_fences(body.splitlines()):
        for m in re.finditer(r"(?<![\w/])references/([\w.-]+\.md)", line):
            rep.err(ref, i, "REF_PATH",
                    f"'references/{m.group(1)}' written inside references/ resolves to "
                    f"references/references/{m.group(1)}; use the bare sibling name")
        for m in re.finditer(r"`([\w.-]+\.md)`", line):
            name = m.group(1)
            if name in ROOT_DOCS or name in siblings or "/" in name or "*" in name:
                continue
            near = difflib.get_close_matches(name, siblings, n=1, cutoff=TYPO_CUTOFF)
            if near:
                rep.err(ref, i, "SIBLING_MISSING",
                        f"points at `{name}`, which is not a file in this references/ "
                        f"directory — did you mean `{near[0]}`?")
            else:
                # Could be a genuine dangling pointer, could be a normal mention
                # of some other document. Not certain enough to block on.
                rep.warn(ref, i, "SIBLING_UNKNOWN",
                         f"names `{name}`, which is not a sibling in this references/ "
                         f"directory — intentional, or a broken pointer?")


def check_map_targets(skill_dir: Path, skill_md: Path, body: str,
                      other_skills: dict[str, Path], rep: Report) -> None:
    """Both `references/x.md` and [text](references/x.md) count as routes.

    A line that names a different skill is routing into *that* skill's tree, so
    it is resolved there and does not count as a local route.
    """
    refdir = skill_dir / "references"
    named: set[str] = set()
    for i, line in outside_fences(body.splitlines()):
        for target in ROUTE_BACKTICK.findall(line) + ROUTE_LINK.findall(line):
            if "*" in target:
                continue
            # Resolve locally first. A line may name another skill for context
            # while still routing into its own tree, so only a path that is
            # missing locally is a candidate for cross-skill ownership.
            if (refdir / target).is_file():
                named.add(target)
                continue
            owner = _cross_skill_owner(line, skill_dir.name, other_skills)
            if owner is not None:
                if not (owner / "references" / target).is_file():
                    rep.err(skill_md, i, "MAP_MISSING",
                            f"routes to {owner.name}'s references/{target}, "
                            f"which does not exist")
                continue
            named.add(target)
            rep.err(skill_md, i, "MAP_MISSING",
                    f"routes to references/{target}, which does not exist")
    if refdir.is_dir():
        for ref in sorted(refdir.glob("*.md")):
            if ref.name not in named:
                rep.err(skill_md, "-", "MAP_UNROUTED",
                        f"references/{ref.name} exists but SKILL.md never routes to it")


def _cross_skill_owner(line: str, current: str, other_skills: dict[str, Path]) -> Path | None:
    """If the line names another skill, that skill owns the reference path on it."""
    for name, path in other_skills.items():
        if name != current and re.search(rf"`{re.escape(name)}`", line):
            return path
    return None


def check_header_claims(ref: Path, head: str, spine_lc: str, rep: Report) -> None:
    head_lc = head.lower()
    if "skill.md" not in head_lc:
        return
    for phrase, pattern in SPINE_CLAIMS.items():
        if phrase in head_lc and not re.search(pattern, spine_lc, re.M):
            rep.err(ref, 1, "HEADER_CLAIM",
                    f"header says SKILL.md carries '{phrase}', but that spine has no such section")


def check_sufficiency(path: Path, lines: list[str], rep: Report) -> None:
    """Warn only: a document must be able to quote the anti-pattern it forbids."""
    start = strip_frontmatter(lines)
    for i, line in outside_fences(lines):
        if i <= start:
            continue
        if SUFFICIENCY_STRONG.search(line) or (
                SUFFICIENCY_WEAK.search(line) and SUFFICIENCY_CONTEXT.search(line)):
            rep.warn(path, i, "SUFFICIENCY",
                     "reads as a claim that the spine is sufficient on its own — "
                     "unverifiable and repeatedly false; route to references instead")


def check_positional(path: Path, lines: list[str], rep: Report) -> None:
    start = strip_frontmatter(lines)
    for i, line in outside_fences(lines):
        if i <= start or re.search(r"\d\s*%|below \d|above \d", line, re.I):
            continue
        if POSITIONAL.search(line):
            rep.warn(path, i, "POSITIONAL",
                     f"positional cross-reference — name the section: {line.strip()[:70]}")


def check_headings(path: Path, body: str, expect_h1: bool, rep: Report) -> None:
    levels = [(i, len(m.group(1)))
              for i, line in outside_fences(body.splitlines())
              if (m := re.match(r"(#{1,6}) \S", line))]
    if not levels:
        return
    if expect_h1 and levels[0][1] != 1:
        rep.err(path, levels[0][0], "NO_H1",
                f"file should open at H1, opens at H{levels[0][1]}")
    for (li, a), (_, b) in zip(levels, levels[1:]):
        if b - a > 1:
            rep.err(path, li, "HEADING_JUMP", f"heading level jumps H{a} -> H{b}")


def check_skill_names(path: Path, body: str, known: set[str], rep: Report) -> None:
    """Only a near-miss on a real skill name is certain enough to block.

    Anything else backticked near the word "skill" is overwhelmingly prose — a
    table name, a library, an event type — so it warns at most.
    """
    for i, line in outside_fences(body.splitlines()):
        for m in re.finditer(r"`([a-z0-9][a-z0-9-]*)`", line):
            name = m.group(1)
            if name in known or NOT_A_SKILL.search(name):
                continue
            esc = re.escape(name)
            explicit = any(re.search(t.format(name=esc), line, re.I) for t in SKILL_EXPLICIT)
            if not (explicit or re.search(SKILL_ARROW.format(name=esc), line)):
                continue
            near = difflib.get_close_matches(name, known, n=1, cutoff=TYPO_CUTOFF)
            if near:
                rep.err(path, i, "UNKNOWN_SKILL",
                        f"routes to `{name}`, which does not exist — "
                        f"did you mean `{near[0]}`?")
            elif explicit:
                rep.warn(path, i, "UNKNOWN_SKILL",
                         f"reads as a skill route, but `{name}` is not a known skill "
                         f"or agent — prose, or a broken route?")


def check_frontmatter(skill_md: Path, raw: str, expected: str, rep: Report) -> None:
    if not raw.startswith("---\n"):
        rep.err(skill_md, 1, "FRONTMATTER", "missing YAML frontmatter")
        return
    end = raw.find("\n---\n", 3)
    if end == -1:
        rep.err(skill_md, 1, "FRONTMATTER", "frontmatter not terminated")
        return
    fm = raw[4:end]
    m = re.search(r"^name:\s*[\"']?([^\"'\s]+)[\"']?\s*$", fm, re.M)
    if not m:
        rep.err(skill_md, 1, "FRONTMATTER", "frontmatter has no name:")
    elif m.group(1) != expected:
        rep.err(skill_md, 1, "FRONTMATTER",
                f"frontmatter name '{m.group(1)}' != directory '{expected}'")
    if not re.search(r"^description:\s*\S", fm, re.M):
        rep.err(skill_md, 1, "FRONTMATTER", "frontmatter has no description:")


# ── driver ───────────────────────────────────────────────────────────────

def _scope_filter(scope: Path | None, skills_dir: Path, agents_dir: Path):
    """Return (skill_predicate, agent_predicate) for --scope.

    Scoping to the edited file is what keeps one skill's drift from blocking an
    unrelated edit. With no scope, everything is checked.
    """
    if scope is None:
        return (lambda d: True), (lambda a: True)
    scope = scope.resolve()
    try:
        rel = scope.relative_to(skills_dir.resolve())
        target = rel.parts[0] if rel.parts else None
        return (lambda d: d.name == target), (lambda a: False)
    except ValueError:
        pass
    try:
        scope.relative_to(agents_dir.resolve())
        return (lambda d: False), (lambda a: a.resolve() == scope)
    except ValueError:
        return (lambda d: False), (lambda a: False)


def lint(skills_dir: Path, agents_dir: Path, scope: Path | None = None,
         transient_ok: bool = False) -> tuple[list[Finding], list[Finding]]:
    rep = Report(transient_ok=transient_ok)
    subdirs = sorted(d for d in skills_dir.iterdir() if d.is_dir())
    skills = [d for d in subdirs if (d / "SKILL.md").is_file()]
    by_name = {d.name: d for d in skills}

    known = set(by_name) | set(BUILTIN_SKILLS)
    if agents_dir.is_dir():
        known |= {a.stem for a in agents_dir.glob("*.md")}

    want_skill, want_agent = _scope_filter(scope, skills_dir, agents_dir)

    # A directory that looks like a skill but has no spine is dropped from every
    # other check, so its whole reference tree would lint clean by vanishing.
    for d in subdirs:
        if d.name in by_name or not want_skill(d):
            continue
        if (d / "references").is_dir() or any(d.glob("*.md")):
            rep.err(d / "SKILL.md", "-", "MISSING_SPINE",
                    "directory holds skill content but has no SKILL.md, so nothing "
                    "in it is linted")

    for d in skills:
        if not want_skill(d):
            continue
        skill_md = d / "SKILL.md"
        raw = read(skill_md, rep)
        if raw is None:
            continue
        lines = raw.splitlines()
        broken_fence = check_fences(skill_md, lines, rep)
        check_frontmatter(skill_md, raw, d.name, rep)
        # With a fence left open the map is unreadable, so every route would be
        # reported missing. Report the fence, not the phantoms.
        if not broken_fence:
            check_map_targets(d, skill_md, raw, by_name, rep)
        check_sufficiency(skill_md, lines, rep)
        check_positional(skill_md, lines, rep)
        check_headings(skill_md, raw, expect_h1=False, rep=rep)
        check_skill_names(skill_md, raw, known, rep)

        refdir = d / "references"
        if not refdir.is_dir():
            continue
        siblings = {p.name for p in refdir.glob("*.md")}
        spine_lc = raw.lower()
        for ref in sorted(refdir.glob("*.md")):
            rb = read(ref, rep)
            if rb is None:
                continue
            rlines = rb.splitlines()
            check_fences(ref, rlines, rep)
            check_reference_paths(ref, rb, siblings, rep)
            check_header_claims(ref, "\n".join(rlines[:12]), spine_lc, rep)
            check_sufficiency(ref, rlines, rep)
            check_positional(ref, rlines, rep)
            check_headings(ref, rb, expect_h1=True, rep=rep)
            check_skill_names(ref, rb, known, rep)

    if agents_dir.is_dir():
        for agent in sorted(agents_dir.glob("*.md")):
            if not want_agent(agent):
                continue
            ab = read(agent, rep)
            if ab is not None:
                check_skill_names(agent, ab, known, rep)

    return rep.errors, rep.warnings


def main() -> int:
    ap = argparse.ArgumentParser(description="Lint the skill tree.")
    ap.add_argument("--skills-dir", type=Path, default=DEFAULT_SKILLS)
    ap.add_argument("--agents-dir", type=Path, default=DEFAULT_AGENTS)
    ap.add_argument("--scope", type=Path, default=None,
                    help="limit checks to the skill (or agent file) containing PATH")
    ap.add_argument("--transient-ok", action="store_true",
                    help="downgrade the map checks, which a half-finished edit trips")
    ap.add_argument("--quiet", action="store_true", help="suppress warnings")
    args = ap.parse_args()

    if not args.skills_dir.is_dir():
        print(f"no such skills dir: {args.skills_dir}", file=sys.stderr)
        return EXIT_BAD_INVOCATION
    if not args.agents_dir.is_dir():
        # Silently linting nothing is how a path typo disables the agent checks
        # forever while the summary still says "no errors".
        print(f"warn  agents dir not found, agent prompts unchecked: {args.agents_dir}",
              file=sys.stderr)

    errors, warnings = lint(args.skills_dir, args.agents_dir,
                            scope=args.scope, transient_ok=args.transient_ok)
    if not args.quiet:
        for w in warnings:
            print(f"warn  {w}")
    for e in errors:
        print(f"ERROR {e}")

    n_skills = sum(1 for d in args.skills_dir.iterdir() if (d / "SKILL.md").is_file())
    n_refs = len(list(args.skills_dir.glob("*/references/*.md")))
    scope = f"{n_skills} skills, {n_refs} reference files"
    if errors:
        print(f"\n{len(errors)} error(s), {len(warnings)} warning(s) across {scope}")
        return EXIT_FINDINGS
    print(f"no errors: {scope}, {len(warnings)} warning(s)")
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
