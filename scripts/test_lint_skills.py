#!/usr/bin/env python3
"""Fixture tests for lint_skills.

Each test builds a throwaway skill tree containing a known defect (or a known
*correct* construct) and asserts the linter's verdict. Written before the
linter was fixed, so every case here failed at least once.

Two things this suite exists to hold down, both of which shipped broken once:

  - The ERROR/WARN split. A check that blocks must be mechanically certain.
    Every "…is prose, not a defect" case below is a false positive that once
    blocked every edit under skills/.
  - The agents branch. It used to be handed a nonexistent directory by every
    fixture, so it had zero coverage while a path typo silently disabled agent
    linting for good.

Run: python3 scripts/test_lint_skills.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lint_skills import lint  # noqa: E402

FM = "---\nname: {name}\ndescription: a test skill\n---\n\n# {name}\n\n"

_failures: list[str] = []
_passes = 0


def build(tmp: Path, skill: str, spine: str, refs: dict[str, str] | None = None,
          raw_spine: bool = False) -> Path:
    d = tmp / "skills" / skill
    d.mkdir(parents=True, exist_ok=True)
    body = spine if raw_spine else FM.format(name=skill) + spine
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    for fname, content in (refs or {}).items():
        rd = d / "references"
        rd.mkdir(exist_ok=True)
        (rd / fname).write_text(content, encoding="utf-8")
    return d


def agent(tmp: Path, name: str, body: str) -> Path:
    d = tmp / "agents"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.md"
    p.write_text(body, encoding="utf-8")
    return p


def check(label: str, codes: list[str], *, expect: str | None = None,
          forbid: str | None = None) -> None:
    global _passes
    if expect is not None and expect not in codes:
        _failures.append(f"{label}: expected {expect}, got {codes or '[]'}")
        return
    if forbid is not None and forbid in codes:
        _failures.append(f"{label}: {forbid} should NOT fire, got {codes}")
        return
    _passes += 1


def _run(tmp: Path, **kw):
    return lint(tmp / "skills", tmp / "agents", **kw)


def codes_for(tmp: Path, **kw) -> list[str]:
    return [e.code for e in _run(tmp, **kw)[0]]


def warn_codes_for(tmp: Path, **kw) -> list[str]:
    return [w.code for w in _run(tmp, **kw)[1]]


def run() -> None:
    def fresh() -> Path:
        t = Path(tempfile.mkdtemp(prefix="lintskills-"))
        (t / "skills").mkdir()
        (t / "agents").mkdir()
        return t

    # ── reference paths ──────────────────────────────────────────────────
    t = fresh()
    build(t, "a", "See `references/alpha.md` and `references/beta.md`.\n",
          {"alpha.md": "# A\n\nSee `references/beta.md` from inside references/.\n",
           "beta.md": "# B\n"})
    check("references/x.md inside references/", codes_for(t), expect="REF_PATH")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "See `references/alpha.md` and `references/beta.md`.\n",
          {"alpha.md": "# A\n\nSee `alpah.md` for more.\n", "beta.md": "# B\n"})
    check("typo'd sibling is a hard error", codes_for(t), expect="SIBLING_MISSING")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "See `references/alpha.md` and `references/beta.md`.\n",
          {"alpha.md": "# A\n\nRecord it in `runbook.md` somewhere else.\n",
           "beta.md": "# B\n"})
    check("unrelated .md mention does not block", codes_for(t), forbid="SIBLING_MISSING")
    check("...but is still surfaced as a warning",
          warn_codes_for(t), expect="SIBLING_UNKNOWN")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "See `references/alpha.md`.\n",
          {"alpha.md": "# A\n\nDocument the decision in `README.md` and `CLAUDE.md`.\n"})
    check("root docs are not dangling siblings", codes_for(t), forbid="SIBLING_MISSING")
    check("root docs do not even warn", warn_codes_for(t), forbid="SIBLING_UNKNOWN")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "See `references/alpha.md` and `references/beta.md`.\n",
          {"alpha.md": "# A\n\nSee `beta.md` for the sibling rule.\n", "beta.md": "# B\n"})
    check("bare sibling that exists", codes_for(t), forbid="SIBLING_MISSING")
    shutil.rmtree(t)

    # ── map targets ──────────────────────────────────────────────────────
    t = fresh()
    build(t, "a", "See `references/ghost.md`.\n", {"alpha.md": "# A\n"})
    check("backticked route to missing file", codes_for(t), expect="MAP_MISSING")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "See [ghost rules](references/ghost.md).\n", {"alpha.md": "# A\n"})
    check("markdown-link route to missing file", codes_for(t), expect="MAP_MISSING")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "See [the alpha rules](references/alpha.md).\n", {"alpha.md": "# A\n"})
    check("markdown-link route counts as routing", codes_for(t), forbid="MAP_UNROUTED")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "See [alpha](references/alpha.md#index-hygiene).\n", {"alpha.md": "# A\n"})
    check("fragment anchor still counts as routing",
          codes_for(t), forbid="MAP_UNROUTED")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "See [ghost](references/ghost.md#sec).\n", {"alpha.md": "# A\n"})
    check("dangling route with a fragment is still caught",
          codes_for(t), expect="MAP_MISSING")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "See `./references/alpha.md`.\n", {"alpha.md": "# A\n"})
    check("./ prefixed backtick counts as routing",
          codes_for(t), forbid="MAP_UNROUTED")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "No routes here.\n", {"alpha.md": "# A\n"})
    check("orphan reference", codes_for(t), expect="MAP_UNROUTED")
    shutil.rmtree(t)

    # A two-file edit is unavoidably half-finished at some point; interactive
    # callers must not be blocked mid-refactor.
    t = fresh()
    build(t, "a", "No routes here.\n", {"alpha.md": "# A\n"})
    check("transient_ok downgrades the orphan",
          codes_for(t, transient_ok=True), forbid="MAP_UNROUTED")
    check("...to a warning", warn_codes_for(t, transient_ok=True), expect="MAP_UNROUTED")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "See `references/ghost.md`.\n", {"alpha.md": "# A\n"})
    check("transient_ok downgrades the missing target",
          codes_for(t, transient_ok=True), forbid="MAP_MISSING")
    shutil.rmtree(t)

    # ── cross-skill routes ───────────────────────────────────────────────
    t = fresh()
    build(t, "boot", "See `references/rest-adapter.md`.\n", {"rest-adapter.md": "# R\n"})
    build(t, "a", "Load the `boot` skill and read its `references/rest-adapter.md`.\n")
    check("cross-skill pointer resolves against the owning skill",
          codes_for(t), forbid="MAP_MISSING")
    shutil.rmtree(t)

    t = fresh()
    build(t, "boot", "Nothing here.\n")
    build(t, "a", "Load the `boot` skill and read its `references/ghost.md`.\n")
    check("cross-skill pointer to a missing file is still caught",
          codes_for(t), expect="MAP_MISSING")
    shutil.rmtree(t)

    # Naming another skill for context does not hand it your own routes.
    t = fresh()
    build(t, "other", "Nothing here.\n")
    build(t, "a", "`other` refuses this outright. Detail in `references/alpha.md`.\n",
          {"alpha.md": "# A\n"})
    cs, ws = codes_for(t), warn_codes_for(t)
    check("a local route on a line naming another skill stays local",
          cs, forbid="MAP_MISSING")
    check("...and still counts as routing", cs + ws, forbid="MAP_UNROUTED")
    shutil.rmtree(t)

    # ── header claims ────────────────────────────────────────────────────
    t = fresh()
    build(t, "a", "## Core principles\n\nx\n\nSee `references/alpha.md`.\n",
          {"alpha.md": "# A\n\n`SKILL.md` carries the review checklist and refusals.\n"})
    check("header claims refusals the spine lacks", codes_for(t), expect="HEADER_CLAIM")
    shutil.rmtree(t)

    # ── sufficiency (warn tier) ──────────────────────────────────────────
    t = fresh()
    build(t, "a", "Apply them without loading a reference.\n")
    check("'without LOADING a reference' warns",
          warn_codes_for(t), expect="SUFFICIENCY")
    check("...but never blocks", codes_for(t), forbid="SUFFICIENCY")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "Builds a self-contained HTML file with no external assets.\n")
    check("'self-contained HTML' is not a spine claim",
          warn_codes_for(t), forbid="SUFFICIENCY")
    shutil.rmtree(t)

    # A document must be able to quote the anti-pattern it forbids.
    t = fresh()
    build(t, "a", "See `references/alpha.md`.\n",
          {"alpha.md": "# A\n\nRefuse PRs like this:\n\n```text\n"
                       "this module is self-contained, review without opening any reference\n"
                       "```\n"})
    check("sufficiency phrase inside a fence is not a claim",
          warn_codes_for(t), forbid="SUFFICIENCY")
    shutil.rmtree(t)

    # ── positional ───────────────────────────────────────────────────────
    t = fresh()
    build(t, "a", "See `references/alpha.md`.\n",
          {"alpha.md": "# A\n\nUse the checklist above before approving.\n"})
    check("positional claim inside a reference file",
          warn_codes_for(t), expect="POSITIONAL")
    shutil.rmtree(t)

    # ── fences ───────────────────────────────────────────────────────────
    t = fresh()
    build(t, "a", "See `references/alpha.md`.\n",
          {"alpha.md": "# A\n\n## Two\n\n```yaml\n# application.yml\nfoo: bar\n```\n\n### Three\n"})
    check("# comment inside a fence is not a heading",
          codes_for(t), forbid="HEADING_JUMP")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "See `references/alpha.md`.\n",
          {"alpha.md": "# A\n\n````md\n```java\n// # not a heading\n```\n````\n\n## Two\n"})
    check("nested fences do not invert the state",
          codes_for(t), forbid="HEADING_JUMP")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "See `references/alpha.md`.\n", {"alpha.md": "# A\n\n```java\nint x = 1;\n"})
    cs = codes_for(t)
    check("unterminated fence is named", cs, expect="UNTERMINATED_FENCE")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "```java\nint x = 1;\n\nSee `references/alpha.md`.\n", {"alpha.md": "# A\n"})
    cs = codes_for(t)
    check("unterminated fence in a spine is named", cs, expect="UNTERMINATED_FENCE")
    check("...and does not cascade into phantom orphans", cs, forbid="MAP_UNROUTED")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "See `references/alpha.md`.\n", {"alpha.md": "# A\n\n### Skipped H2\n"})
    check("real H1 -> H3 jump", codes_for(t), expect="HEADING_JUMP")
    shutil.rmtree(t)

    # ── skill names ──────────────────────────────────────────────────────
    t = fresh()
    build(t, "hexagonal-ddd-java", "The real skill.\n")
    build(t, "a", "1. Check boundaries → `hexagonl-ddd-java`.\n")
    check("typo'd arrow-form route", codes_for(t), expect="UNKNOWN_SKILL")
    shutil.rmtree(t)

    t = fresh()
    build(t, "hexagonal-ddd-java", "The real skill.\n")
    build(t, "a", "Load the `hexagonal-ddd-jav` skill first.\n")
    check("typo'd explicit route", codes_for(t), expect="UNKNOWN_SKILL")
    shutil.rmtree(t)

    # Prose that merely sits near the word "skill" is not a route. Each of these
    # blocked every edit under skills/ before the ERROR/WARN split.
    for prose, label in [
        ("This skill relies on the `processed-messages` table.", "a table name"),
        ("The `outbox` pattern in this skill is mandatory.", "a pattern name"),
        ("This skill covers `caffeine` sizing rules.", "a library name"),
        ("Load the `order-created` payload before dispatch.", "an event name"),
    ]:
        t = fresh()
        build(t, "a", prose + "\n")
        check(f"{label} near 'skill' does not block", codes_for(t), forbid="UNKNOWN_SKILL")
        shutil.rmtree(t)

    t = fresh()
    build(t, "a", "The `code-review` skill runs after this one.\n")
    check("route to a built-in skill is accepted",
          codes_for(t), forbid="UNKNOWN_SKILL")
    check("...without even warning", warn_codes_for(t), forbid="UNKNOWN_SKILL")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "- Python logic → `pytest` against the logic functions.\n"
                  "- Put it in `shared` → `shared` has no brakes.\n")
    check("arrow to a tool/package is not a skill route",
          codes_for(t), forbid="UNKNOWN_SKILL")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "Boundary questions → `b`.\n")
    build(t, "b", "The other skill.\n")
    check("valid arrow route to a real skill", codes_for(t), forbid="UNKNOWN_SKILL")
    shutil.rmtree(t)

    # ── agents branch ────────────────────────────────────────────────────
    t = fresh()
    build(t, "hexagonal-ddd-java", "The real skill.\n")
    agent(t, "java-backend-architect", "Load the `hexagonal-ddd-jav` skill first.\n")
    check("agent prompt routing to a typo'd skill", codes_for(t), expect="UNKNOWN_SKILL")
    shutil.rmtree(t)

    t = fresh()
    build(t, "hexagonal-ddd-java", "The real skill.\n")
    agent(t, "java-backend-architect", "Load the `hexagonal-ddd-java` skill first.\n")
    check("agent prompt routing to a real skill", codes_for(t), forbid="UNKNOWN_SKILL")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "Hand off to the `code-reviewer` agent.\n")
    agent(t, "code-reviewer", "I review things.\n")
    check("agent names are part of the known set", codes_for(t), forbid="UNKNOWN_SKILL")
    shutil.rmtree(t)

    # ── scope ────────────────────────────────────────────────────────────
    t = fresh()
    build(t, "a", "Clean skill.\n")
    build(t, "b", "No routes here.\n", {"orphan.md": "# O\n"})
    check("unscoped run sees the other skill's drift",
          codes_for(t), expect="MAP_UNROUTED")
    check("scoped run ignores an unrelated skill",
          codes_for(t, scope=t / "skills" / "a" / "SKILL.md"), forbid="MAP_UNROUTED")
    shutil.rmtree(t)

    # ── missing spine ────────────────────────────────────────────────────
    t = fresh()
    d = t / "skills" / "foo" / "references"
    d.mkdir(parents=True)
    (d / "alpha.md").write_text("# A\n\nSee `ghost.md`.\n", encoding="utf-8")
    check("skill dir with no SKILL.md is reported",
          codes_for(t), expect="MISSING_SPINE")
    shutil.rmtree(t)

    # ── robustness ───────────────────────────────────────────────────────
    t = fresh()
    build(t, "aaa", "See `references/x.md`.\n", {"x.md": "# X\n"})
    (t / "skills" / "aaa" / "references" / "x.md").write_bytes(b"# X\n\nca\xe9 latin-1\n")
    build(t, "zzz", "See `references/nope.md`.\n", {"real.md": "# R\n"})
    cs = codes_for(t)
    check("undecodable file reported, not fatal", cs, expect="UNREADABLE")
    check("later skill still checked after a bad file", cs, expect="MAP_MISSING")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", "A skill with no references at all.\n")
    check("no references/ dir does not crash", codes_for(t), forbid="MAP_UNROUTED")
    shutil.rmtree(t)

    t = fresh()
    d = build(t, "a", "Empty references dir.\n")
    (d / "references").mkdir()
    check("empty references/ dir does not crash", codes_for(t), forbid="MAP_UNROUTED")
    shutil.rmtree(t)

    # ── frontmatter ──────────────────────────────────────────────────────
    t = fresh()
    build(t, "a", "---\nname: wrong-name\ndescription: x\n---\n\n# A\n", raw_spine=True)
    check("frontmatter name != directory", codes_for(t), expect="FRONTMATTER")
    shutil.rmtree(t)

    t = fresh()
    build(t, "a", '---\nname: "a"\ndescription: |-\n  quoted and block\n---\n\n# A\n',
          raw_spine=True)
    check("quoted YAML name is accepted", codes_for(t), forbid="FRONTMATTER")
    shutil.rmtree(t)

    # ── the live tree ────────────────────────────────────────────────────
    # The suite can pass on fixtures while the real tree is red; that gap is how
    # a false-positive class reaches a blocking hook unnoticed.
    root = Path(__file__).resolve().parent.parent
    if (root / "skills").is_dir():
        errs, _ = lint(root / "skills", root / "agents")
        global _passes
        if errs:
            _failures.append("live tree has errors:\n    "
                             + "\n    ".join(str(e) for e in errs[:10]))
        else:
            _passes += 1


if __name__ == "__main__":
    run()
    for f in _failures:
        print(f"FAIL  {f}")
    total = _passes + len(_failures)
    print(f"\n{_passes}/{total} passed")
    sys.exit(1 if _failures else 0)
