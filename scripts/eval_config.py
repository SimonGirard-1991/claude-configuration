#!/usr/bin/env python3
"""Evaluate this Claude Code config: run headless sessions on synthetic fixtures, then
measure which rules and skills reached each context, when, and at what cost.

Commands:
  run CASES.json     Run each case in a fresh copy of its fixture. A real run starts paid
                     sessions, so it needs --yes; --dry-run lists the runs and stops.
  report RESULTS     Recompute the run records and the summary of a results directory, in
                     place, from its saved streams and the sessions' transcripts. A run
                     whose transcript is gone (Claude Code deletes them after
                     cleanupPeriodDays, 30 by default) keeps its stored analysis, marked
                     "analysis_source": "original run".
  analyze SESSION    Print the metrics of one recorded session, by session id.
  scan               Print the metrics of every recorded session, one JSON line each, or
                     totals with --summary. Observation windows are measured with it.

A case's prompt never names a skill the case lists, hyphenated or in plain words. Naming
a skill tests access and content, not selection, so such a case file is refused.

For the main session and for each subagent, a run records:
  - Skill tool invocations, and apart from them, direct reads of a skill's files: a
    SKILL.md read without invoking the skill, other files of a skill not invoked, and
    files read after the skill was invoked in the same context (progressive disclosure);
  - rule injections by hooks/session-rules.sh, over-cap pointers, native rule loads
    (nested_memory), and native loads of a pointer stub (a rule file whose text starts with
    "[rule-stub "); whether the rule was in context before the first file-touching tool
    call; how many copies of the body the context holds after its last compaction, and the
    characters beyond the largest copy. Pointers and stubs are not copies of the body;
  - the trigger file of each native load, from logs/rules.jsonl;
  - cost and tokens from the session's cumulative totals (total_cost_usd, modelUsage),
    which cover subagents and compaction, and the last non-empty answer.

Entries are read in file order. A session rewound in the UI keeps its abandoned branch in
the file, so its counts are an approximation. A Bash call counts as a read of a skill file
when a read verb (cat, head, sed without -i, grep, ...) takes it as an operand, with cd and
simple variable assignments earlier in the same call followed; a redirect target is a
write, not a read. A command shlex cannot parse falls back to splitting on separators.

Expectations are measurements, not assertions: a summary lists unmet ones under "unmet",
judged over the runs that have an analysis, and the exit status stays 0.

Fixtures are written under EVAL_WORK_DIR, which must lie inside $HOME, because
session-rules.sh looks for nested manifests only there. Sessions run
with the user's own settings and MCP servers, so model and effort match daily use unless
--model or --effort says otherwise; variables that mark a parent Claude Code session are
removed from the child's environment. scan leaves out sessions run under EVAL_WORK_DIR and
sessions run inside the config directory itself, unless asked to keep them.

Environment overrides (an empty value means the default):
  CLAUDE_CONFIG_DIR  config root (default ~/.claude)
  CLAUDE_BIN         claude executable (default: claude on PATH)
  EVAL_WORK_DIR      fixture root (default ~/.cache/claude-config-evals)
  EVAL_RESULTS_DIR   results root (default evals/results beside this script's repo)

Exit status: 0 success, 1 a run or an analysis failed, 2 usage error or invalid case file.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()
CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or HOME / ".claude")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or "claude"
WORK_DIR = Path(os.environ.get("EVAL_WORK_DIR") or HOME / ".cache" / "claude-config-evals")
RESULTS_DIR = Path(os.environ.get("EVAL_RESULTS_DIR") or ROOT / "evals" / "results")

FILE_TOOLS = frozenset({"Read", "Edit", "MultiEdit", "Write", "NotebookEdit", "Bash", "Grep",
                        "Glob"})
READ_COMMANDS = frozenset({"cat", "head", "tail", "sed", "less", "more", "grep", "rg", "awk",
                           "nl", "bat"})
INJECTION_HEADER = re.compile(r"^\[session-rules ([a-z]+) [0-9a-f]{8}\]")
OVER_CAP_MARK = "it is not inlined here"
STUB_MARK = "[rule-stub "
BASH_SEPARATORS = frozenset({"&&", "||", "|", ";", "\n", "&", "(", ")", ";;", "|&"})
BASH_REDIRECTS = frozenset({">", ">>", "<", "<<", "<<<", ">&", "&>", "&>>", "<>", ">|"})
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
VARIABLE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
PARENT_SESSION_VARS = frozenset({"CLAUDECODE", "CLAUDE_CODE_SESSION_ID",
                                 "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ATTENDED",
                                 "CLAUDE_PID", "CLAUDE_EFFORT", "AI_AGENT"})
PARENT_SESSION_PREFIXES = ("CLAUDE_CODE_MESSAGING_",)
EXPECT_KEYS = frozenset({"rules_loaded", "rules_not_loaded", "skills_load", "skills_not_load"})
SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")
DEFAULT_TIMEOUT_S = 600
DEFAULT_REPEATS = 3

Json = dict[str, Any]


class CaseError(Exception):
    pass


def skill_path_pattern() -> re.Pattern[str]:
    prefixes = [re.escape(str(CONFIG_DIR / "skills"))]
    if CONFIG_DIR == HOME / ".claude":
        prefixes += [re.escape("~/.claude/skills"), re.escape("$HOME/.claude/skills"),
                     re.escape("${HOME}/.claude/skills")]
    return re.compile("(?:" + "|".join(prefixes)
                      + r")/(?:synced/[^/\s'\"]+/)?([A-Za-z0-9_.-]+)/([^\s'\";|&]*)")


def read_jsonl(path: Path) -> list[Json]:
    entries = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def rule_loads(entry: Json) -> list[tuple[str, str, int]]:
    if entry.get("type") != "attachment":
        return []
    attachment = entry.get("attachment") or {}
    kind = attachment.get("type")
    if kind == "hook_additional_context":
        content = attachment.get("content")
        loads = []
        for text in content if isinstance(content, list) else [content]:
            if not isinstance(text, str):
                continue
            match = INJECTION_HEADER.match(text)
            if match:
                mechanism = "pointer" if OVER_CAP_MARK in text else "injected"
                loads.append((match.group(1), mechanism, len(text)))
        return loads
    if kind == "nested_memory":
        path = Path(attachment.get("path") or "")
        if path.parent == CONFIG_DIR / "rules" and path.suffix == ".md":
            content = attachment.get("content")
            if isinstance(content, dict):
                content = content.get("content")
            text = content if isinstance(content, str) else ""
            mechanism = "stub" if text.lstrip().startswith(STUB_MARK) else "native"
            return [(path.stem, mechanism, len(text))]
    return []


def tool_uses(entry: Json) -> list[Json]:
    if entry.get("type") != "assistant":
        return []
    content = (entry.get("message") or {}).get("content") or []
    return [block for block in content
            if isinstance(block, dict) and block.get("type") == "tool_use"]


def bash_words(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    commands: list[list[str]] = [[]]
    for token in lexer:
        if token in BASH_SEPARATORS:
            commands.append([])
        else:
            commands[-1].append(token)
    return [words for words in commands if words]


def anchored(path: str) -> bool:
    return path.startswith(("/", "~", "$HOME", "${HOME}"))


def bash_read_operands(command: str) -> list[str]:
    try:
        commands = bash_words(command)
    except ValueError:
        return [segment for segment in re.split(r"\|\||&&|[|;\n]", command)
                if segment.split() and Path(segment.split()[0]).name in READ_COMMANDS]
    cwd: str | None = None
    variables: dict[str, str] = {}
    operands: list[str] = []
    for words in commands:
        while words and ASSIGNMENT.match(words[0]):
            name, value = words[0].split("=", 1)
            variables[name] = value
            words = words[1:]
        if not words:
            continue
        words = [VARIABLE.sub(lambda m: variables.get(m.group(1), m.group(0)), word)
                 for word in words]
        verb = Path(words[0]).name
        if verb == "cd" and len(words) > 1:
            target = words[1]
            cwd = target if anchored(target) or cwd is None else f"{cwd.rstrip('/')}/{target}"
            continue
        if verb not in READ_COMMANDS or (verb == "sed" and any(
                word.startswith(("-i", "--in-place")) for word in words[1:])):
            continue
        skip = False
        for word in words[1:]:
            if skip:
                skip = False
            elif word in BASH_REDIRECTS:
                skip = True
            elif not word.startswith("-"):
                operands.append(word if anchored(word) or cwd is None
                                else f"{cwd.rstrip('/')}/{word}")
    return operands


def read_targets(name: str, tool_input: Json) -> list[str]:
    if name == "Read":
        return [str(tool_input.get("file_path") or "")]
    if name == "Grep":
        return [str(tool_input.get("path") or "")]
    if name == "Bash":
        return bash_read_operands(str(tool_input.get("command") or ""))
    return []


def analyze_context(entries: list[Json]) -> Json:
    skill_re = skill_path_pattern()
    first_file_tool = None
    loads: list[tuple[int, str, str, int, str | None]] = []
    boundaries: list[tuple[int, set[str]]] = []
    invoked: Counter[str] = Counter()
    md_without_invoke: Counter[str] = Counter()
    other_without_invoke: Counter[str] = Counter()
    after_invoke: Counter[str] = Counter()
    tools: list[str] = []
    for index, entry in enumerate(entries):
        if entry.get("type") == "system" and entry.get("subtype") == "compact_boundary":
            preserved = ((entry.get("compactMetadata") or {}).get("preservedMessages") or {})
            boundaries.append((index, set(preserved.get("allUuids") or [])))
        for rule, mechanism, chars in rule_loads(entry):
            loads.append((index, rule, mechanism, chars, entry.get("uuid")))
        for block in tool_uses(entry):
            name = str(block.get("name"))
            tools.append(name)
            if first_file_tool is None and name in FILE_TOOLS:
                first_file_tool = index
            tool_input = block.get("input") or {}
            if name == "Skill":
                invoked[str(tool_input.get("skill"))] += 1
                continue
            touched: dict[str, bool] = {}
            for target in read_targets(name, tool_input):
                for skill, rest in skill_re.findall(target):
                    touched[skill] = touched.get(skill, False) or rest == "SKILL.md"
            for skill, is_skill_md in touched.items():
                if invoked[skill]:
                    after_invoke[skill] += 1
                elif is_skill_md:
                    md_without_invoke[skill] += 1
                else:
                    other_without_invoke[skill] += 1
    last_boundary, preserved = boundaries[-1] if boundaries else (-1, set())
    rules: dict[str, Json] = {}
    for index, rule, mechanism, chars, entry_uuid in loads:
        stats = rules.setdefault(rule, {"injected": 0, "pointer": 0, "native": 0, "stub": 0,
                                        "copies_in_context": 0, "chars_in_context": 0,
                                        "largest_copy": 0, "before_first_file_tool": False})
        stats[mechanism] += 1
        is_body = mechanism in ("injected", "native")
        if is_body and (index > last_boundary or entry_uuid in preserved):
            stats["copies_in_context"] += 1
            stats["chars_in_context"] += chars
            stats["largest_copy"] = max(stats["largest_copy"], chars)
        if first_file_tool is None or index < first_file_tool:
            stats["before_first_file_tool"] = True
    for stats in rules.values():
        stats["excess_chars"] = stats["chars_in_context"] - stats.pop("largest_copy")
    return {"rules": rules, "skills_invoked": dict(invoked),
            "skill_md_read_without_invoke": dict(md_without_invoke),
            "skill_files_read_without_invoke": dict(other_without_invoke),
            "skill_files_read_after_invoke": dict(after_invoke),
            "compactions": len(boundaries), "tools": tools}


def find_transcript(session_id: str) -> Path | None:
    matches = sorted((CONFIG_DIR / "projects").glob(f"*/{session_id}.jsonl"))
    return matches[0] if matches else None


@functools.lru_cache(maxsize=1)
def native_trigger_index() -> dict[str, list[Json]]:
    log = CONFIG_DIR / "logs" / "rules.jsonl"
    index: dict[str, list[Json]] = {}
    if log.is_file():
        for entry in read_jsonl(log):
            if entry.get("load_reason") == "path_glob_match":
                index.setdefault(str(entry.get("session_id")), []).append(
                    {"file": entry.get("file_path"), "trigger": entry.get("trigger_file_path")})
    return index


def analyze_transcript(main: Path) -> Json:
    entries = read_jsonl(main)
    session_id = main.stem
    cwd = next((e.get("cwd") for e in entries if e.get("cwd")), None)
    started = next((e.get("timestamp") for e in entries if e.get("timestamp")), None)
    version = next((e.get("version") for e in entries if e.get("version")), None)
    subagents = []
    for path in sorted((main.parent / session_id / "subagents").glob("*.jsonl")):
        meta_path = path.with_name(path.stem + ".meta.json")
        agent_type = None
        if meta_path.is_file():
            try:
                agent_type = json.loads(meta_path.read_text(encoding="utf-8")).get("agentType")
            except (OSError, json.JSONDecodeError, AttributeError):
                agent_type = None
        subagents.append({"agent": path.stem, "type": agent_type,
                          **analyze_context(read_jsonl(path))})
    return {"session_id": session_id, "cwd": cwd, "started": started, "version": version,
            "main": analyze_context(entries), "subagents": subagents,
            "native_triggers": native_trigger_index().get(session_id, [])}


def analyze_session(session_id: str) -> Json:
    main = find_transcript(session_id)
    if main is None:
        raise FileNotFoundError(f"no transcript for session {session_id} under {CONFIG_DIR}")
    return analyze_transcript(main)


def stream_result(stdout: str) -> Json:
    result: Json = {"model": None, "is_error": False, "result_events": 0, "text": None,
                    "cumulative_cost_usd": None, "cumulative_tokens": None}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            result["model"] = event.get("model")
        elif event.get("type") == "result":
            result["result_events"] += 1
            result["is_error"] = result["is_error"] or bool(event.get("is_error"))
            if event.get("result"):
                result["text"] = event["result"]
            if event.get("total_cost_usd") is not None:
                result["cumulative_cost_usd"] = event["total_cost_usd"]
            if isinstance(event.get("modelUsage"), dict):
                totals: Counter[str] = Counter()
                for usage in event["modelUsage"].values():
                    for key in ("inputTokens", "outputTokens", "cacheReadInputTokens",
                                "cacheCreationInputTokens"):
                        totals[key] += int((usage or {}).get(key) or 0)
                result["cumulative_tokens"] = dict(totals)
    return result


def check_work_dir() -> Path:
    work = WORK_DIR.resolve()
    home = HOME.resolve()
    if work == home or home not in work.parents:
        raise CaseError(f"EVAL_WORK_DIR must lie inside $HOME, not be it: {work}")
    return work


def names_skill(prompt: str, skill: str) -> bool:
    words = [re.escape(part) for part in re.split(r"[-_]+", skill) if part]
    pattern = r"(?<![\w-])" + r"[-_\s]+".join(words) + r"(?![\w-])"
    return re.search(pattern, prompt, re.IGNORECASE) is not None


def check_case(case: object, fixtures: Json, seen: set[str]) -> None:
    if not isinstance(case, dict):
        raise CaseError(f"every case must be an object, got {case!r}")
    case_id = case.get("id")
    if not isinstance(case_id, str) or not SLUG.fullmatch(case_id):
        raise CaseError(f"case {case_id!r}: 'id' must be a lowercase slug")
    if case_id in seen:
        raise CaseError(f"case {case_id}: duplicate id")
    seen.add(case_id)
    if case.get("fixture") not in fixtures:
        raise CaseError(f"case {case_id}: unknown fixture {case.get('fixture')!r}")
    repeats = case.get("repeats")
    if repeats is not None and (isinstance(repeats, bool) or not isinstance(repeats, int)
                                or repeats < 1):
        raise CaseError(f"case {case_id}: 'repeats' must be a positive integer")
    steps = case.get("steps")
    if not isinstance(steps, list) or not steps or not all(
            isinstance(step, str) and step.strip() for step in steps):
        raise CaseError(f"case {case_id}: 'steps' must be a non-empty list of prompts")
    expect = case.get("expect", {})
    if not isinstance(expect, dict) or set(expect) - EXPECT_KEYS:
        raise CaseError(f"case {case_id}: 'expect' takes only {', '.join(sorted(EXPECT_KEYS))}")
    for key, names in expect.items():
        if not isinstance(names, list) or not all(
                isinstance(name, str) and SLUG.fullmatch(name) for name in names):
            raise CaseError(f"case {case_id}: expect.{key} must be a list of slugs")
    for skill in set(expect.get("skills_load", [])) | set(expect.get("skills_not_load", [])):
        if any(names_skill(step, skill) for step in steps):
            raise CaseError(f"case {case_id}: a prompt names skill {skill!r}; a named skill "
                            "tests access and content, not selection")


def load_cases(path: Path) -> Json:
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CaseError(f"{path}: {error}") from error
    if not isinstance(spec, dict):
        raise CaseError(f"{path}: the top level must be an object")
    if not isinstance(spec.get("addition"), str) or not SLUG.fullmatch(spec["addition"]):
        raise CaseError(f"{path}: 'addition' must be a lowercase slug")
    fixtures = spec.get("fixtures")
    cases = spec.get("cases")
    if not isinstance(fixtures, dict) or not isinstance(cases, list) or not cases:
        raise CaseError(f"{path}: needs a 'fixtures' object and a non-empty 'cases' list")
    for name, files in fixtures.items():
        if not isinstance(files, dict) or not files or not all(
                isinstance(text, str) for text in files.values()):
            raise CaseError(f"fixture {name}: must map relative paths to file contents")
        for rel in files:
            parts = Path(rel).parts
            if (Path(rel).is_absolute() or not parts or ".." in parts
                    or any(part.lower() == ".git" for part in parts)):
                raise CaseError(f"fixture {name}: path {rel!r} escapes the fixture")
    seen: set[str] = set()
    for case in cases:
        check_case(case, fixtures, seen)
    return spec


def materialize(files: dict[str, str], target: Path) -> None:
    for rel, text in files.items():
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)


def remove_run_dir(path: Path, work: Path) -> None:
    resolved = path.resolve()
    if work not in resolved.parents:
        raise RuntimeError(f"refusing to delete {resolved}: outside {work}")
    shutil.rmtree(resolved)


def child_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items()
            if key not in PARENT_SESSION_VARS and not key.startswith(PARENT_SESSION_PREFIXES)}


def claude_command(prompt: str, session_id: str, first: bool, args: argparse.Namespace
                   ) -> list[str]:
    command = [CLAUDE_BIN, "-p", prompt, "--output-format", "stream-json", "--verbose"]
    command += ["--session-id", session_id] if first else ["--resume", session_id]
    if args.model:
        command += ["--model", args.model]
    if args.effort:
        command += ["--effort", args.effort]
    if args.max_budget_usd is not None:
        command += ["--max-budget-usd", str(args.max_budget_usd)]
    return command


def run_steps(case: Json, session_id: str, run_dir: Path, out_dir: Path,
              args: argparse.Namespace) -> list[Json]:
    steps: list[Json] = []
    for index, prompt in enumerate(case["steps"]):
        try:
            proc = subprocess.run(claude_command(prompt, session_id, index == 0, args),
                                  cwd=run_dir, env=child_environment(), capture_output=True,
                                  text=True, timeout=args.timeout, check=False)
            stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as expired:
            partial = expired.stdout or b""
            stdout = partial.decode("utf-8", "replace") if isinstance(partial, bytes) else partial
            stderr = f"timed out after {args.timeout}s"
            code = None
        (out_dir / f"step-{index}.jsonl").write_text(stdout, encoding="utf-8")
        (out_dir / f"step-{index}.err").write_text(stderr, encoding="utf-8")
        steps.append({"prompt": prompt, "exit": code, **stream_result(stdout)})
        if code != 0 or steps[-1]["is_error"]:
            break
    return steps


def run_record(case: Json, repeat: int, session_id: str, steps: list[Json],
               error: str | None, analysis: Json | None = None,
               analysis_source: str | None = None) -> Json:
    if analysis is None and error is None:
        try:
            analysis, analysis_source = analyze_session(session_id), "transcript"
        except FileNotFoundError as missing:
            error = str(missing)
    failed = (error is not None or len(steps) < len(case["steps"])
              or any(step["exit"] != 0 or step["is_error"] for step in steps))
    return {"case": case["id"], "repeat": repeat, "session_id": session_id,
            "fixture": case["fixture"], "expect": case.get("expect", {}), "failed": failed,
            "error": error, "steps": steps, "analysis": analysis,
            "analysis_source": analysis_source}


def run_once(spec: Json, case: Json, repeat: int, args: argparse.Namespace, work: Path,
             out_dir: Path) -> Json:
    session_id = str(uuid.uuid4())
    run_dir = work / f"{spec['addition']}-{case['id']}-r{repeat}-{session_id[:8]}"
    run_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    steps: list[Json] = []
    error = None
    try:
        try:
            materialize(spec["fixtures"][case["fixture"]], run_dir)
        except (OSError, subprocess.CalledProcessError) as broken:
            error = f"fixture not written: {broken}"
        if error is None:
            steps = run_steps(case, session_id, run_dir, out_dir, args)
    finally:
        if not args.keep:
            remove_run_dir(run_dir, work)
    record = run_record(case, repeat, session_id, steps, error)
    (out_dir / "run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def rule_view(context: Json, rule: str) -> Json:
    stats: Json = context["rules"].get(rule) or {}
    return stats


def loaded(context: Json, rule: str) -> bool:
    stats = rule_view(context, rule)
    return bool(stats.get("injected", 0) + stats.get("native", 0))


def skill_touched(context: Json, skill: str) -> bool:
    return bool(context["skills_invoked"].get(skill)
                or context["skill_md_read_without_invoke"].get(skill)
                or context["skill_files_read_without_invoke"].get(skill)
                or context["skill_files_read_after_invoke"].get(skill))


def context_groups(analysis: Json) -> dict[str, list[Json]]:
    groups: dict[str, list[Json]] = {"main": [analysis["main"]]}
    for agent in analysis["subagents"]:
        groups.setdefault(f"subagent:{agent['type'] or 'unknown'}", []).append(agent)
    return groups


def summarize(case: Json, runs: list[Json]) -> Json:
    expect = case.get("expect") or {}
    analyses = [run["analysis"] for run in runs if run["analysis"]]
    summary: Json = {"case": case["id"], "runs": len(runs),
                     "failed": sum(run["failed"] for run in runs),
                     "runs without analysis": len(runs) - len(analyses), "unmet": []}
    rules = sorted({rule for a in analyses for group in context_groups(a).values()
                    for ctx in group for rule in ctx["rules"]}
                   | set(expect.get("rules_loaded", [])) | set(expect.get("rules_not_loaded", [])))
    contexts: Json = {}
    for analysis in analyses:
        for label, group in context_groups(analysis).items():
            view = contexts.setdefault(label, {"runs present": 0, "rules": {}})
            view["runs present"] += 1
            for rule in rules:
                row = view["rules"].setdefault(rule, Counter())
                row["runs injected"] += any(rule_view(c, rule).get("injected") for c in group)
                row["runs pointer"] += any(rule_view(c, rule).get("pointer") for c in group)
                row["runs stub"] += any(rule_view(c, rule).get("stub") for c in group)
                row["runs native"] += any(rule_view(c, rule).get("native") for c in group)
                row["runs before first file tool"] += any(
                    rule_view(c, rule).get("before_first_file_tool") for c in group)
                row["runs with 2+ copies"] += any(
                    rule_view(c, rule).get("copies_in_context", 0) > 1 for c in group)
                row["max excess chars"] = max(row["max excess chars"], *(
                    rule_view(c, rule).get("excess_chars", 0) for c in group))
    summary["contexts"] = {label: {"runs present": view["runs present"],
                                   "rules": {r: dict(c) for r, c in view["rules"].items()
                                             if any(c.values())}}
                           for label, view in contexts.items()}
    mains = [analysis["main"] for analysis in analyses]
    everywhere = [[analysis["main"], *analysis["subagents"]] for analysis in analyses]
    judged = len(analyses)
    for rule in expect.get("rules_loaded", []):
        hits = sum(loaded(main, rule) for main in mains)
        if hits < judged:
            summary["unmet"].append(f"rule {rule} loaded in main: {hits}/{judged}")
    for rule in expect.get("rules_not_loaded", []):
        hits = sum(loaded(main, rule) for main in mains)
        if hits:
            summary["unmet"].append(f"rule {rule} not loaded in main: loaded in {hits}/{judged}")
    skills: Json = {}
    for skill in expect.get("skills_load", []) + expect.get("skills_not_load", []):
        skills[skill] = {
            "runs invoked": sum(any(c["skills_invoked"].get(skill) for c in ctx)
                                for ctx in everywhere),
            "runs SKILL.md read without invoke": sum(
                any(c["skill_md_read_without_invoke"].get(skill) for c in ctx)
                for ctx in everywhere),
            "runs other files read without invoke": sum(
                any(c["skill_files_read_without_invoke"].get(skill) for c in ctx)
                for ctx in everywhere),
            "runs files read after invoke": sum(
                any(c["skill_files_read_after_invoke"].get(skill) for c in ctx)
                for ctx in everywhere)}
    summary["skills"] = skills
    for skill in expect.get("skills_load", []):
        hits = sum(any(skill_touched(c, skill) for c in ctx) for ctx in everywhere)
        if hits < judged:
            summary["unmet"].append(f"skill {skill} loaded: {hits}/{judged}")
    for skill in expect.get("skills_not_load", []):
        hits = sum(any(skill_touched(c, skill) for c in ctx) for ctx in everywhere)
        if hits:
            summary["unmet"].append(f"skill {skill} not loaded: loaded in {hits}/{judged}")
    finals = [next((s for s in reversed(run["steps"]) if s.get("cumulative_cost_usd") is not None),
                   None) for run in runs]
    costs = [final["cumulative_cost_usd"] for final in finals if final]
    if costs:
        summary["total cost usd"] = round(sum(costs), 4)
        summary["mean cost usd per run"] = round(sum(costs) / len(costs), 4)
    tokens = [final["cumulative_tokens"] for final in finals
              if final and final.get("cumulative_tokens")]
    if tokens:
        summary["mean tokens per run"] = {key: round(sum(t.get(key, 0) for t in tokens)
                                                     / len(tokens))
                                          for key in sorted({k for t in tokens for k in t})}
    return summary


def selected_cases(spec: Json, args: argparse.Namespace) -> list[Json]:
    cases: list[Json] = spec["cases"]
    if args.case:
        unknown = set(args.case) - {case["id"] for case in cases}
        if unknown:
            raise CaseError(f"unknown case id(s): {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case["id"] in args.case]
    return cases


def write_summaries(results: Path, summaries: list[Json]) -> None:
    (results / "summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    for summary in summaries:
        print(json.dumps(summary))


def command_run(args: argparse.Namespace) -> int:
    spec = load_cases(Path(args.cases))
    cases = selected_cases(spec, args)
    work = check_work_dir()
    plan = [(case, repeat) for case in cases
            for repeat in range(1, (args.repeats or case.get("repeats") or DEFAULT_REPEATS) + 1)]
    if args.dry_run:
        for case, repeat in plan:
            print(f"{case['id']} r{repeat}: fixture {case['fixture']}, "
                  f"{len(case['steps'])} step(s), model {args.model or 'settings'}, "
                  f"effort {args.effort or 'settings'}")
        print(f"{len(plan)} run(s), {sum(len(c['steps']) for c, _ in plan)} session step(s); "
              f"fixtures under {work}, results under {RESULTS_DIR}")
        return 0
    if not args.yes:
        print("eval_config: a real run starts paid sessions; pass --yes, or --dry-run to "
              "list them", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results = RESULTS_DIR / f"{stamp}-{spec['addition']}"
    by_case: dict[str, list[Json]] = {case["id"]: [] for case in cases}
    for case, repeat in plan:
        print(f"running {case['id']} r{repeat}", file=sys.stderr)
        by_case[case["id"]].append(
            run_once(spec, case, repeat, args, work, results / f"{case['id']}-r{repeat}"))
    summaries = [summarize(case, by_case[case["id"]]) for case in cases]
    write_summaries(results, summaries)
    print(f"results: {results}", file=sys.stderr)
    return 1 if any(summary["failed"] for summary in summaries) else 0


def command_report(args: argparse.Namespace) -> int:
    results = Path(args.results)
    known = {}
    if args.cases:
        known = {case["id"]: case for case in load_cases(Path(args.cases))["cases"]}
    records = sorted(results.glob("*/run.json"))
    if not records:
        raise CaseError(f"{results}: no run records")
    by_case: dict[str, list[Json]] = {}
    cases: dict[str, Json] = {}
    for path in records:
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            case = known.get(old["case"]) or {"id": old["case"], "fixture": old["fixture"],
                                              "steps": [s["prompt"] for s in old["steps"]],
                                              "expect": old.get("expect", {})}
            steps = []
            for index, step in enumerate(old["steps"]):
                stream = path.parent / f"step-{index}.jsonl"
                steps.append({"prompt": step["prompt"], "exit": step["exit"],
                              **stream_result(stream.read_text(encoding="utf-8"))}
                             if stream.is_file() else step)
            session_id, repeat = old["session_id"], old["repeat"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as broken:
            raise CaseError(f"{path}: not a run record ({broken})") from broken
        source: str | None
        try:
            analysis, source = analyze_session(session_id), "transcript"
        except FileNotFoundError:
            analysis = old.get("analysis")
            source = "original run" if analysis is not None else None
        error = None if analysis is not None else old.get("error") or "no analysis"
        record = run_record(case, repeat, session_id, steps, error, analysis, source)
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        by_case.setdefault(case["id"], []).append(record)
        cases[case["id"]] = case
    summaries = [summarize(cases[case_id], runs) for case_id, runs in by_case.items()]
    write_summaries(results, summaries)
    return 1 if any(summary["failed"] for summary in summaries) else 0


def command_analyze(args: argparse.Namespace) -> int:
    try:
        print(json.dumps(analyze_session(args.session_id), indent=2))
    except FileNotFoundError as missing:
        print(f"eval_config: {missing}", file=sys.stderr)
        return 1
    return 0


def excluded(cwd: Path | None, args: argparse.Namespace) -> bool:
    if cwd is None:
        return False
    cwd = cwd.resolve()
    for root, keep in ((WORK_DIR.resolve(), args.include_evals),
                       (CONFIG_DIR.resolve(), args.include_config)):
        if not keep and (cwd == root or root in cwd.parents):
            return True
    return False


def command_scan(args: argparse.Namespace) -> int:
    totals: Json = {"sessions": 0, "rules": {}, "skills": {}}
    for main in sorted((CONFIG_DIR / "projects").glob("*/*.jsonl")):
        report = analyze_transcript(main)
        if excluded(Path(report["cwd"]) if report["cwd"] else None, args):
            continue
        if args.since and (report["started"] or "") < args.since:
            continue
        if not args.summary:
            print(json.dumps(report))
            continue
        totals["sessions"] += 1
        for rule, stats in report["main"]["rules"].items():
            row = totals["rules"].setdefault(rule, Counter())
            row["sessions injected"] += stats["injected"] > 0
            row["sessions native in main"] += stats["native"] > 0
            row["sessions with 2+ copies"] += stats["copies_in_context"] > 1
            row["excess chars"] += stats["excess_chars"]
        for agent in report["subagents"]:
            for rule, stats in agent["rules"].items():
                totals["rules"].setdefault(rule, Counter())[
                    f"native loads in subagent:{agent['type'] or 'unknown'}"] += stats["native"]
        contexts = [report["main"], *report["subagents"]]
        for metric in ("skills_invoked", "skill_md_read_without_invoke",
                       "skill_files_read_without_invoke", "skill_files_read_after_invoke"):
            for skill in {s for context in contexts for s in context[metric]}:
                totals["skills"].setdefault(skill, Counter())[f"sessions {metric}"] += 1
    if args.summary:
        print(json.dumps(totals, indent=2))
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="eval_config.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a case file")
    run.add_argument("cases", help="path to a cases.json file")
    run.add_argument("--case", action="append", help="run only this case id (repeatable)")
    run.add_argument("--repeats", type=int,
                     help=f"runs per case (default: the case's own, else {DEFAULT_REPEATS})")
    run.add_argument("--model", help="model override (default: the user's settings)")
    run.add_argument("--effort", help="effort override (default: the user's settings)")
    run.add_argument("--max-budget-usd", type=float,
                     help="spend cap passed to each claude -p process")
    run.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S,
                     help=f"seconds per session step (default {DEFAULT_TIMEOUT_S})")
    run.add_argument("--keep", action="store_true", help="keep each fixture copy")
    run.add_argument("--dry-run", action="store_true", help="list the runs and stop")
    run.add_argument("--yes", action="store_true", help="confirm a real, paid run")
    report = commands.add_parser("report", help="recompute a results directory")
    report.add_argument("results", help="a results directory written by run")
    report.add_argument("--cases", help="the case file, for records written without "
                        "their expectations")
    analyze = commands.add_parser("analyze", help="metrics of one recorded session")
    analyze.add_argument("session_id")
    scan = commands.add_parser("scan", help="metrics of every recorded session")
    scan.add_argument("--since", help="only sessions started at or after this ISO date")
    scan.add_argument("--summary", action="store_true", help="print totals, not sessions")
    scan.add_argument("--include-evals", action="store_true",
                      help="keep sessions run under EVAL_WORK_DIR")
    scan.add_argument("--include-config", action="store_true",
                      help="keep sessions run inside the config directory")
    args = parser.parse_args(argv)
    if getattr(args, "repeats", None) is not None and args.repeats < 1:
        parser.error("--repeats must be at least 1")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    handlers = {"run": command_run, "report": command_report, "analyze": command_analyze,
                "scan": command_scan}
    try:
        return handlers[args.command](args)
    except CaseError as invalid:
        print(f"eval_config: {invalid}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
