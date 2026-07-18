#!/usr/bin/env python3
"""Build a self-contained System Design quiz HTML from a JSON data file.

Usage:
    build_quiz.py DATA.json [--out DIR] [--template PATH]

Injects validated question data into the tested HTML/JS engine template and
writes <out>/<slug>.html. Fails loudly if the data is malformed (e.g. an MCQ
without exactly one correct option, or an empty field), so a broken or
mis-keyed quiz can never ship. Stdlib only; no third-party dependencies.
"""
from __future__ import annotations
import argparse
import html as _html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = HERE.parent / "assets" / "template.html"


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def need(cond: bool, msg: str) -> None:
    if not cond:
        die(msg)


def esc(s: object) -> str:
    """Escape &, <, > for safe interpolation into element text."""
    return _html.escape(str(s), quote=False)


def vstr(d: dict, key: str, where: str) -> str:
    v = d.get(key)
    need(isinstance(v, str) and v.strip() != "", f"{where}: missing or empty '{key}'")
    return v


def validate_mcq(item: dict, where: str, senior: bool = False) -> None:
    vstr(item, "ch", where)
    vstr(item, "theme", where)
    vstr(item, "q", where)
    vstr(item, "ex", where)
    opts = item.get("opts")
    need(isinstance(opts, list) and 2 <= len(opts) <= 4,
         f"{where}: 'opts' must be a list of 2-4 entries")
    n_correct = 0
    for j, o in enumerate(opts):
        need(isinstance(o, dict), f"{where} opt[{j}]: must be an object")
        vstr(o, "t", f"{where} opt[{j}]")
        if o.get("c") is True:
            n_correct += 1
        else:
            o["c"] = False  # normalise so the engine's find(o=>o.c) skips it
    need(n_correct == 1,
         f"{where}: needs exactly one correct option (c:true), found {n_correct}")
    if senior:
        item["tier"] = "senior"


def validate_open(item: dict, where: str) -> None:
    need(item.get("type") == "open", f"{where}: whiteboard item needs \"type\":\"open\"")
    vstr(item, "ch", where)
    vstr(item, "theme", where)
    vstr(item, "q", where)
    vstr(item, "trap", where)
    pts = item.get("points")
    need(isinstance(pts, list) and len(pts) >= 2, f"{where}: 'points' needs >= 2 entries")
    for j, p in enumerate(pts):
        need(isinstance(p, str) and p.strip() != "", f"{where} points[{j}]: empty")


def as_js_array(value: object) -> str:
    """Serialise to JSON (valid JS) and neutralise any </script> breakout."""
    return json.dumps(value, ensure_ascii=False, indent=2).replace("</", "<\\/")


def visible_len(text: str) -> int:
    """Length of the rendered text, ignoring HTML tags."""
    return len(re.sub(r"<[^>]+>", "", text).strip())


def check_length_bias(mcqs: list, fail_over: float = 0.35, warn_over: float = 0.20) -> None:
    """Guard against the #1 quiz tell: the correct option being the longest.

    If a test-taker can score well by always picking the longest answer, the quiz
    is broken regardless of how good the questions read. Fails the build when the
    correct option is >25% longer than every distractor in too many questions.
    """
    if not mcqs:
        return
    longest = 0
    guessable = []  # (where, ratio)
    for where, q in mcqs:
        opts = q["opts"]
        correct = next(o for o in opts if o.get("c") is True)
        distractors = [o for o in opts if o.get("c") is not True]
        c_len = visible_len(correct["t"])
        d_max = max((visible_len(o["t"]) for o in distractors), default=0)
        if d_max and c_len > d_max:
            longest += 1
        if d_max and c_len > 1.25 * d_max:
            guessable.append((where, round(c_len / d_max, 2)))
    n = len(mcqs)
    frac = len(guessable) / n
    print(f"    length check   : correct is longest in {longest}/{n}; "
          f"guessable-by-length {len(guessable)}/{n} ({frac:.0%})")
    if frac > warn_over:
        preview = ", ".join(f"{w}(x{r})" for w, r in guessable[:10])
        msg = (f"length bias: the correct option is >25% longer than every distractor in "
               f"{len(guessable)}/{n} MCQs ({frac:.0%}) — a test-taker can score high by "
               f"always picking the longest answer. Match option lengths and make distractors "
               f"subtly wrong (a single precise flaw), not short throwaways. Offenders: {preview}")
        if frac > fail_over:
            die(msg)
        print("warn: " + msg, file=sys.stderr)


def chapter_labels(chapters: list) -> dict:
    """Map a chapter number to its display name from "2.03 · Load Balancing" chips.

    Used by the engine only when a quiz spans more than one chapter, to label the
    per-chapter sub-modes. Entries that don't follow "<num> · <name>" are skipped.
    """
    labels = {}
    for c in chapters:
        parts = c.split("·", 1)  # middot separator
        if len(parts) == 2 and parts[0].strip():
            labels[parts[0].strip()] = parts[1].strip()
    return labels


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a quiz HTML from a JSON data file.")
    ap.add_argument("data", help="path to the quiz-data JSON file")
    ap.add_argument("--out", default="quizzes", help="output directory (default: quizzes)")
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE), help="engine template path")
    args = ap.parse_args()

    data_path = Path(args.data)
    need(data_path.is_file(), f"data file not found: {data_path}")
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"invalid JSON in {data_path}: {e}")

    meta = data.get("meta") or {}
    slug = vstr(meta, "slug", "meta")
    need(re.fullmatch(r"[A-Za-z0-9._-]+", slug) is not None,
         "meta.slug must be a safe filename (letters, digits, . _ -)")
    vstr(meta, "title", "meta")
    vstr(meta, "subtitle", "meta")
    vstr(meta, "footer", "meta")
    chapters = meta.get("chapters")
    themes = meta.get("themes")
    need(isinstance(chapters, list) and len(chapters) > 0, "meta.chapters must be a non-empty list")
    need(isinstance(themes, list) and len(themes) > 0, "meta.themes must be a non-empty list")

    questions = data.get("questions") or []
    senior = data.get("senior") or []
    whiteboard = data.get("whiteboard") or []
    interviewer = data.get("interviewer") or []
    need(len(questions) > 0, "no 'questions' (foundation MCQs) provided")

    for i, q in enumerate(questions):
        validate_mcq(q, f"questions[{i}]")
    for i, q in enumerate(senior):
        validate_mcq(q, f"senior[{i}]", senior=True)
    for i, w in enumerate(whiteboard):
        validate_open(w, f"whiteboard[{i}]")
    for i, v in enumerate(interviewer):
        vstr(v, "ch", f"interviewer[{i}]")
        vstr(v, "q", f"interviewer[{i}]")
        vstr(v, "a", f"interviewer[{i}]")

    # Refuse to ship a quiz that can be gamed by answer length.
    check_length_bias([(f"questions[{i}]", q) for i, q in enumerate(questions)]
                      + [(f"senior[{i}]", q) for i, q in enumerate(senior)])

    tpl = Path(args.template).read_text(encoding="utf-8")
    replacements = {
        "__TITLE__": esc(meta["title"]),
        "__BRAND__": esc(meta.get("brand") or "Quiz"),  # header brand; corpus quizzes set "System Design Quiz"
        "__SUBTITLE__": esc(meta["subtitle"]),
        "__FOOTER_SOURCE__": meta["footer"],  # HTML allowed (e.g. <b>...</b>)
        "__CHAPTERS_CHIPS__": "".join(f'<span class="chip src">{esc(c)}</span>' for c in chapters),
        "__THEMES_CHIPS__": "".join(f'<span class="chip">{esc(t)}</span>' for t in themes),
        "__CHAPTER_LABELS__": as_js_array(chapter_labels(chapters)),
        "__QUESTIONS__": as_js_array(questions),
        "__SENIOR__": as_js_array(senior),
        "__WHITEBOARD__": as_js_array(whiteboard),
        "__INTERVIEWER__": as_js_array(interviewer),
    }
    out = tpl
    for key, val in replacements.items():
        need(key in out, f"template is missing placeholder {key}")
        out = out.replace(key, val)
    leftover = [k for k in replacements if k in out]
    need(not leftover, f"template has unfilled placeholders: {leftover}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{slug}.html"
    dest.write_text(out, encoding="utf-8")

    playable = len(questions) + len(senior) + len(whiteboard)
    print(f"OK  {dest}")
    print(f"    foundation MCQ : {len(questions)}")
    print(f"    senior tells   : {len(senior)}")
    print(f"    whiteboard     : {len(whiteboard)}")
    print(f"    interviewer Qs : {len(interviewer)}")
    print(f"    themes         : {len(themes)}    playable items: {playable}")
    print("    note           : mechanical checks passed; these do NOT verify answer "
          "defensibility — run the adversarial semantic pass (see references/question-design.md)")
    if len(questions) < 8:
        print("warn: fewer than 8 foundation MCQs — chapter may be under-covered", file=sys.stderr)
    if not interviewer:
        print("warn: no interviewer questions provided (panel will be empty)", file=sys.stderr)


if __name__ == "__main__":
    main()
