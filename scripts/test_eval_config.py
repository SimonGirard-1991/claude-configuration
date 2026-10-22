#!/usr/bin/env python3
"""Fixture tests for scripts/eval_config.py.

A fake claude executable stands in for the real one. It prints the stream events the
harness parses, with the semantics measured on CLI 2.1.307: total_cost_usd and
modelUsage accumulate over a session across --resume, and a background agent leaves
extra result events, the last one with empty text. It also appends a canned transcript
under a throwaway CLAUDE_CONFIG_DIR, so the suite spends nothing and never touches the
live config. Transcript entries copy the shapes of real ones: a nested_memory content is
an object, and an injection's content is a list of strings. The tables pin both
directions: what the analysis must count, and what it must leave out.

Run: python3 scripts/test_eval_config.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_CONFIG = os.environ.get("CLAUDE_EVAL_CONFIG", str(ROOT / "scripts" / "eval_config.py"))

_passes = 0
_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global _passes
    if ok:
        _passes += 1
    else:
        _failures.append(f"{name}: {detail}" if detail else name)


FAKE_CLAUDE = """#!{python}
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
prompt = args[args.index("-p") + 1]
first = "--session-id" in args
session_id = args[args.index("--session-id" if first else "--resume") + 1]
config = Path(os.environ["CLAUDE_CONFIG_DIR"])
planted = json.loads(os.environ["FAKE_PLANTED"])
with open(os.environ["FAKE_CALLS"], "a") as calls:
    calls.write(json.dumps({{"argv": args, "cwd": os.getcwd(),
                             "env": {{k: os.environ.get(k) for k in planted}}}}) + "\\n")
state = Path(os.environ["FAKE_STATE"]) / (session_id + ".json")
spent = json.loads(state.read_text()) if state.exists() else {{"cost": 0.0, "out": 0}}
spent["cost"] = round(spent["cost"] + (0.02 if prompt == "background" else 0.01), 4)
spent["out"] += 7
state.parent.mkdir(parents=True, exist_ok=True)
state.write_text(json.dumps(spent))

def result(text, is_error=False, out=5):
    return json.dumps({{"type": "result", "is_error": is_error, "result": text,
                       "total_cost_usd": spent["cost"],
                       "usage": {{"input_tokens": 3, "output_tokens": out}},
                       "modelUsage": {{
                           "fake-main": {{"inputTokens": 3, "outputTokens": spent["out"],
                                          "cacheReadInputTokens": 100,
                                          "cacheCreationInputTokens": 50}},
                           "fake-reviewer": {{"inputTokens": 1, "outputTokens": 2}}}}}})

if prompt == "fail":
    print(result("boom", is_error=True))
    sys.exit(1)
project = config / "projects" / "fake"
if first:
    project.mkdir(parents=True, exist_ok=True)
    with open(project / (session_id + ".jsonl"), "a") as transcript:
        for line in open(os.environ["FAKE_TRANSCRIPT"]):
            entry = json.loads(line)
            entry["cwd"] = os.getcwd()
            transcript.write(json.dumps(entry) + "\\n")
    subagent = os.environ.get("FAKE_SUBAGENT")
    if subagent:
        target = project / session_id / "subagents"
        target.mkdir(parents=True, exist_ok=True)
        (target / "agent-f1.jsonl").write_text(open(subagent).read())
        (target / "agent-f1.meta.json").write_text(json.dumps({{"agentType": "code-reviewer"}}))
print(json.dumps({{"type": "system", "subtype": "init", "session_id": session_id,
                  "model": "fake-model"}}))
if prompt == "background":
    print(result("interim answer"))
    print(result("final answer"))
    print(result("", out=0))
elif prompt == "soft-error":
    print(result("refused", is_error=True))
elif prompt == "error-then-ok":
    print(result("refused", is_error=True))
    print(result("recovered"))
else:
    print(result("DONE"))
"""


def attachment(kind: str, uid: str, **fields: object) -> dict:
    return {"type": "attachment", "uuid": uid, "isSidechain": False,
            "attachment": {"type": kind, **fields}}


def native(uid: str, path: Path, body: str) -> dict:
    return attachment("nested_memory", uid, path=str(path), displayPath=str(path),
                      content={"path": str(path), "type": "User", "content": body})


def injection(uid: str, *texts: str) -> dict:
    return attachment("hook_additional_context", uid, content=list(texts),
                      hookName="SessionStart", hookEvent="SessionStart")


def tool(name: str, tool_input: dict, tool_id: str = "") -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tool_id or f"t-{name}", "name": name, "input": tool_input}]}}


def result(tool_id: str, uid: str, text: str, kind: str = "text", is_error: bool = False) -> dict:
    return {"type": "user", "uuid": uid, "toolUseResult": {"type": kind},
            "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id,
                                     "content": text, "is_error": is_error}]}}


def boundary(*preserved: str) -> dict:
    return {"type": "system", "subtype": "compact_boundary", "isSidechain": False,
            "compactMetadata": {"trigger": "manual",
                                "preservedMessages": {"allUuids": list(preserved)}}}


JAVA_1 = "[session-rules java 0123abcd] The user's Java conventions follow. Body one."
JAVA_2 = "[session-rules java 0123abcd] Java again"
JAVA_3 = "[session-rules java 0123abcd] Java third, a little longer than the second"
FRONTEND_1 = "[session-rules frontend 89abcdef] The user's React/Next conventions follow."
FRONTEND_POINTER = ("[session-rules frontend 89abcdef] The user's React/Next conventions live "
                    "in ~/.claude/rules/frontend.md, which is over the hook output cap; it is "
                    "not inlined here.")


PLANTED = {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "parent",
           "CLAUDE_CODE_CHILD_SESSION": "1", "CLAUDE_CODE_SESSION_ATTENDED": "1",
           "CLAUDE_PID": "123", "CLAUDE_EFFORT": "xhigh", "AI_AGENT": "claude-code",
           "CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/x", "CLAUDE_CODE_MESSAGING_TOKEN": "t",
           "KEEP_ME": "1"}

BASH_SHAPES = [
    "cd ~/.claude/skills/hexagonal-ddd-java/references && cat layer-rules.md",
    "grep -n -i -E 'xxe|zip;x' ~/.claude/skills/java-security-baseline/references/a.md",
    "F=$HOME/.claude/skills/java-performance-patterns/SKILL.md; grep -n '^#' $F",
    "awk '{print $1; next}' ~/.claude/skills/client-comms/references/b.md | head",
    "head -n 3 ${HOME}/.claude/skills/braced/SKILL.md",
    ("echo 'unbalanced && ls ~/.claude/skills/fallback-ls/"
     " && cat ~/.claude/skills/fallback/SKILL.md"),
    "cat > ~/.claude/skills/written/SKILL.md <<EOF\nhello\nEOF",
    "sed -i '' 's/a/b/' ~/.claude/skills/edited/SKILL.md",
    "ls ~/.claude/skills/scoping/\ncat ~/.claude/skills/newline/SKILL.md",
    "cat < ~/.claude/skills/stdin-read/SKILL.md",
    "echo 'unbalanced; cat > ~/.claude/skills/fallback-written/SKILL.md",
    "cd ~/.claude/skills/x-up/references && cd ../../dotdot/references && cat ../SKILL.md",
    "cd ~/.claude/skills && cd relcd && head SKILL.md",
    "A=1 B=$HOME/.claude/skills/multi-assign/SKILL.md; head $B",
    'export F=~/.claude/skills/exported/SKILL.md; cat "$F"',
    "D=~/.claude/skills; F=$D/chained/SKILL.md; tail $F",
    ("for f in ~/.claude/skills/loop-a/SKILL.md ~/.claude/skills/loop-b/references/x.md; "
     'do head -n 3 "$f"; done'),
]


def main_transcript(config: Path) -> list[dict]:
    skills = config / "skills"
    return [
        injection("u0", JAVA_1, FRONTEND_1, "Another hook: [session-rules java 0123abcd] quoted"),
        {"type": "user", "message": {"content": "a prompt"}},
        tool("Skill", {"skill": "java-financial-correctness"}),
        native("u3", config / "rules" / "early.md", "e" * 10),
        tool("Read", {"file_path": str(skills / "md2pdf" / "SKILL.md")}),
        native("u5", config / "rules" / "java.md", "x" * 100),
        tool("Bash", {"command": "cat ~/.claude/skills/quiz/references/a.md"}),
        tool("Read", {"file_path": str(skills / "java-financial-correctness" / "references"
                                       / "money.md")}),
        tool("Bash", {"command": "ls ~/.claude/skills/scoping/ && "
                                 "wc -l $HOME/.claude/skills/scoping/SKILL.md"}),
        tool("Bash", {"command": "head -n 5 $HOME/.claude/skills/adr/SKILL.md"}),
        tool("Read", {"file_path": str(skills / "synced" / "abc123" / "pdf" / "SKILL.md")}),
        *[tool("Bash", {"command": command}) for command in BASH_SHAPES],
        tool("Grep", {"pattern": "x", "path": str(skills / "grepped" / "references")}),
        native("u10", config / "rules" / "stubbed.md",
               "[rule-stub stubbed] Read ~/.claude/conventions/stubbed.md first."),
        boundary("u5"),
        injection("u12", JAVA_2),
        boundary("u12"),
        injection("u14", JAVA_3),
        native("u15", config.parent / "other" / "rules" / "java.md", "not the user's rule"),
        injection("u16", FRONTEND_POINTER),
        tool("Glob", {"pattern": str(skills / "scoping" / "*")}),
    ]


def subagent_transcript(config: Path) -> list[dict]:
    return [tool("Bash", {"command": "cat src/A.java"}),
            native("s1", config / "rules" / "frontend.md", "y" * 40),
            tool("Skill", {"skill": "java-testing-strategy"})]


def write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


def cases_file(path: Path, cases: object, fixtures: dict | None = None) -> Path:
    spec = {"addition": "test-addition",
            "fixtures": fixtures or {"java": {"pom.xml": "<project/>",
                                              "src/Main.java": "class Main {}"}},
            "cases": cases}
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def test_analysis(run, config: Path) -> None:
    sid = "11111111-2222-3333-4444-555555555555"
    write_jsonl(config / "projects" / "p" / f"{sid}.jsonl", main_transcript(config))
    write_jsonl(config / "projects" / "p" / sid / "subagents" / "agent-a1.jsonl",
                subagent_transcript(config))
    (config / "projects" / "p" / sid / "subagents" / "agent-a1.meta.json").write_text(
        json.dumps({"agentType": "code-reviewer"}), encoding="utf-8")
    write_jsonl(config / "logs" / "rules.jsonl", [
        {"session_id": sid, "load_reason": "path_glob_match",
         "file_path": str(config / "rules" / "java.md"), "trigger_file_path": "/x/A.java"},
        {"session_id": sid, "load_reason": "session_start", "file_path": "CLAUDE.md"},
        {"session_id": "other", "load_reason": "path_glob_match", "file_path": "z"}])

    proc = run("analyze", sid)
    report = json.loads(proc.stdout) if proc.returncode == 0 else {}
    main = report.get("main", {})
    rules = main.get("rules", {})
    java, frontend, early = rules.get("java", {}), rules.get("frontend", {}), rules.get("early", {})
    check("analyze: injections count only headers that open a string",
          java.get("injected") == 3 and frontend.get("injected") == 1, json.dumps(rules))
    check("analyze: an over-cap pointer is told apart from an injection",
          frontend.get("pointer") == 1, json.dumps(frontend))
    check("analyze: a native load of the user's rule counts, another rules/ dir does not",
          java.get("native") == 1 and early.get("native") == 1, json.dumps(rules))
    check("analyze: copies follow the last compaction: later loads plus what it preserved",
          java.get("copies_in_context") == 2, json.dumps(rules))
    check("analyze: an over-cap pointer after compaction is not a copy of the body",
          frontend.get("copies_in_context") == 0, json.dumps(frontend))
    check("analyze: excess characters are the copies beyond the largest one",
          java.get("chars_in_context") == len(JAVA_2) + len(JAVA_3)
          and java.get("excess_chars") == len(JAVA_2)
          and frontend.get("excess_chars") == 0, json.dumps(java))
    check("analyze: a native load's size is its rule text, not the attachment object",
          early.get("chars_in_context") == 0 and early.get("excess_chars") == 0
          and rules.get("early", {}).get("copies_in_context") == 0, json.dumps(early))
    check("analyze: a Skill call is not a file tool, so a load after it is still early",
          early.get("before_first_file_tool") is True
          and java.get("before_first_file_tool") is True, json.dumps(rules))
    check("analyze: Skill invocations are counted apart from every kind of direct read",
          main.get("skills_invoked") == {"java-financial-correctness": 1}
          and main.get("skill_files_read_after_invoke") == {"java-financial-correctness": 1},
          json.dumps(main))
    check("analyze: SKILL.md reads without an invocation, through Read, Bash and variables",
          main.get("skill_md_read_without_invoke") == {
              "md2pdf": 1, "adr": 1, "pdf": 1, "java-performance-patterns": 1, "braced": 1,
              "fallback": 1, "newline": 1, "stdin-read": 1, "dotdot": 1, "relcd": 1,
              "multi-assign": 1, "exported": 1, "chained": 1, "loop-a": 1},
          json.dumps(main.get("skill_md_read_without_invoke")))
    check("analyze: other skill files read without an invocation, after cd, quoted | and ;",
          main.get("skill_files_read_without_invoke") == {
              "quiz": 1, "hexagonal-ddd-java": 1, "java-security-baseline": 1,
              "client-comms": 1, "grepped": 1, "loop-b": 1},
          json.dumps(main.get("skill_files_read_without_invoke")))
    check("analyze: ls, wc, Glob, a redirect target, sed -i and a path before ../ are not reads",
          not any(name in json.dumps(main) for name in ("scoping", "written", "edited",
                                                        "fallback-ls", "fallback-written",
                                                        "x-up")),
          json.dumps(main))
    check("analyze: a synced skill keeps its own name",
          "synced" not in json.dumps(main.get("skill_md_read_without_invoke")),
          json.dumps(main.get("skill_md_read_without_invoke")))
    stubbed = rules.get("stubbed", {})
    check("analyze: a pointer stub is its own mechanism and not a copy of the body",
          stubbed.get("stub") == 1 and stubbed.get("native") == 0
          and stubbed.get("copies_in_context") == 0, json.dumps(stubbed))
    check("analyze: a stub compacted away is no longer in context",
          stubbed.get("stubs_in_context") == 0, json.dumps(stubbed))
    check("analyze: compactions are counted", main.get("compactions") == 2, json.dumps(main))
    sub = (report.get("subagents") or [{}])[0]
    sub_frontend = sub.get("rules", {}).get("frontend", {})
    check("analyze: a subagent is reported apart, with its type and its own loads",
          sub.get("type") == "code-reviewer" and sub_frontend.get("native") == 1
          and sub_frontend.get("chars_in_context") == 40
          and sub.get("skills_invoked") == {"java-testing-strategy": 1}, json.dumps(sub))
    check("analyze: Bash is a file tool, so a load after a Bash read is not early",
          sub_frontend.get("before_first_file_tool") is False, json.dumps(sub_frontend))
    check("analyze: native-load triggers come from this session's path-glob lines only",
          report.get("native_triggers") == [{"file": str(config / "rules" / "java.md"),
                                              "trigger": "/x/A.java"}],
          json.dumps(report.get("native_triggers")))
    proc = run("analyze", "00000000-0000-0000-0000-000000000000")
    check("analyze: an unknown session exits 1", proc.returncode == 1, proc.stderr)

    late_sid = "99999999-2222-3333-4444-555555555555"
    write_jsonl(config / "projects" / "p" / f"{late_sid}.jsonl", [
        {"type": "user", "cwd": "/somewhere", "message": {"content": "go"}},
        tool("Read", {"file_path": "/somewhere/App.tsx"}),
        native("l1", config / "rules" / "late.md", "z"),
        native("l2", config / "rules" / "java.md", "native only, never injected")])
    proc = run("analyze", late_sid)
    late = json.loads(proc.stdout)["main"]["rules"].get("late", {}) if proc.returncode == 0 else {}
    check("analyze: a rule first loaded after a file tool is not marked as early",
          late.get("before_first_file_tool") is False, proc.stdout[-300:])

    reads_sid = "88888888-2222-3333-4444-555555555555"
    body = "1\t# Java conventions\n2\tRecords for value objects.\n"
    write_jsonl(config / "projects" / "p" / f"{reads_sid}.jsonl", [
        {"type": "user", "cwd": "/work", "message": {"content": "review it"}},
        injection("b0", FRONTEND_POINTER),
        native("b1", config / "rules" / "kotlin.md", "\n[rule-stub kotlin] Read the body."),
        native("b2", config / "rules" / "kotlin.md", "[rule-stub kotlin] Read the body."),
        tool("Read", {"file_path": str(config / "conventions" / "java.md")}, "r1"),
        result("r1", "b3", body),
        tool("Read", {"file_path": str(config / "conventions" / "java.md")}, "r2"),
        result("r2", "b4", "Unchanged since the earlier read.", kind="file_unchanged"),
        tool("Bash", {"command": "cat ~/.claude/conventions/swift.md"}, "r3"),
        result("r3", "b5", "cat: no such file", is_error=True),
        tool("Bash", {"command": "cat ~/.claude/conventions/kotlin.md > /tmp/copy.md"}, "r6"),
        result("r6", "b8", ""),
        tool("Read", {"file_path": "/work/App.java"}, "r4"),
        result("r4", "b6", "class App {}"),
        tool("Bash", {"command": "cd ~/.claude/conventions && head -n 5 frontend.md"}, "r5"),
        result("r5", "b7", "# Frontend")])
    proc = run("analyze", reads_sid)
    read_rules = json.loads(proc.stdout)["main"]["rules"] if proc.returncode == 0 else {}
    java_read, kotlin = read_rules.get("java", {}), read_rules.get("kotlin", {})
    check("analyze: a Read of a body is a copy of its own mechanism, a repeat notice is not",
          java_read.get("read") == 1 and java_read.get("copies_in_context") == 1
          and java_read.get("chars_in_context") == len(body), json.dumps(java_read))
    check("analyze: a failed read of a body loads nothing", "swift" not in read_rules,
          json.dumps(read_rules))
    check("analyze: a Bash read of a body after cd counts too",
          read_rules.get("frontend", {}).get("read") == 1, json.dumps(read_rules.get("frontend")))
    check("analyze: a stub after leading whitespace is still a stub, and stubs are counted",
          kotlin.get("stub") == 2 and kotlin.get("native") == 0
          and kotlin.get("stubs_in_context") == 2, json.dumps(kotlin))
    check("analyze: a body read that printed nothing loads nothing",
          kotlin.get("read") == 0 and kotlin.get("copies_in_context") == 0, json.dumps(kotlin))
    check("analyze: only a body makes a rule early, and reading a body is not the first file tool",
          java_read.get("before_first_file_tool") is True
          and kotlin.get("before_first_file_tool") is False
          and read_rules.get("frontend", {}).get("before_first_file_tool") is False,
          json.dumps(read_rules))

    config_sid = "77777777-2222-3333-4444-555555555555"
    write_jsonl(config / "projects" / "c" / f"{config_sid}.jsonl", [
        {"type": "user", "cwd": str(config), "message": {"content": "edit a skill"}},
        injection("c1", JAVA_1)])


def test_case_validation(run, home: Path) -> None:
    rows = [
        ("an expected skill named with hyphens",
         [{"id": "c1", "fixture": "java", "steps": ["Use Java-Financial-Correctness here"],
           "expect": {"skills_load": ["java-financial-correctness"]}}], "names skill"),
        ("an expected skill named in plain words",
         [{"id": "c1", "fixture": "java", "steps": ["apply the java testing strategy skill"],
           "expect": {"skills_load": ["java-testing-strategy"]}}], "names skill"),
        ("a skill that must stay unloaded, named",
         [{"id": "c1", "fixture": "java", "steps": ["run md2pdf on it"],
           "expect": {"skills_not_load": ["md2pdf"]}}], "names skill"),
        ("a misspelled expect key",
         [{"id": "c1", "fixture": "java", "steps": ["go"],
           "expect": {"skill_load": ["md2pdf"]}}], "takes only"),
        ("an expect value that is a string",
         [{"id": "c1", "fixture": "java", "steps": ["go"],
           "expect": {"skills_load": "java-testing-strategy"}}], "list of slugs"),
        ("a case that is not an object", ["c1"], "must be an object"),
        ("repeats as a string",
         [{"id": "c1", "fixture": "java", "steps": ["go"], "repeats": "2"}], "positive integer"),
        ("repeats of zero",
         [{"id": "c1", "fixture": "java", "steps": ["go"], "repeats": 0}], "positive integer"),
        ("negative repeats",
         [{"id": "c1", "fixture": "java", "steps": ["go"], "repeats": -1}], "positive integer"),
        ("a duplicate id",
         [{"id": "c1", "fixture": "java", "steps": ["go"]},
          {"id": "c1", "fixture": "java", "steps": ["go"]}], "duplicate"),
        ("an unknown fixture",
         [{"id": "c1", "fixture": "nope", "steps": ["go"]}], "unknown fixture"),
        ("empty steps", [{"id": "c1", "fixture": "java", "steps": []}], "steps"),
        ("a misspelled rubric key",
         [{"id": "c1", "fixture": "java", "steps": ["go"], "rubric": {"must_flag": ["x"]}}],
         "'rubric' takes only"),
        ("an empty rubric list",
         [{"id": "c1", "fixture": "java", "steps": ["go"], "rubric": {"must_find": []}}],
         "'rubric' takes only"),
        ("a rubric item that is not a description",
         [{"id": "c1", "fixture": "java", "steps": ["go"], "rubric": {"must_find": [3]}}],
         "'rubric' takes only"),
    ]
    for name, cases, message in rows:
        proc = run("run", str(cases_file(home / "case.json", cases)), "--dry-run")
        check(f"cases: refuses {name}", proc.returncode == 2 and message in proc.stderr,
              f"exit {proc.returncode}, stderr {proc.stderr[-300:]!r}")
    for rel in ("../outside.txt", ".git/hooks/pre-commit", "sub/.git/hooks/pre-commit",
                ".GIT/hooks/post-checkout", "/etc/passwd"):
        proc = run("run", str(cases_file(home / "case.json",
                                         [{"id": "c1", "fixture": "java", "steps": ["go"]}],
                                         fixtures={"java": {rel: "x"}})), "--dry-run")
        check(f"cases: refuses fixture path {rel}",
              proc.returncode == 2 and "escapes" in proc.stderr, proc.stderr[-300:])
    (home / "array.json").write_text("[]", encoding="utf-8")
    proc = run("run", str(home / "array.json"), "--dry-run")
    check("cases: a top-level array exits 2", proc.returncode == 2 and "top level" in proc.stderr,
          proc.stderr[-300:])
    proc = run("run", str(home / "missing.json"), "--dry-run")
    check("cases: an unreadable case file exits 2", proc.returncode == 2, proc.stderr[-300:])
    proc = run("run", str(cases_file(home / "case.json", [
        {"id": "c1", "fixture": "java", "steps": ["Round this java-financial amount"],
         "expect": {"skills_load": ["java-financial-correctness"]}}])), "--dry-run")
    check("cases: a prefix of a skill name is not naming it", proc.returncode == 0,
          proc.stderr[-300:])


def test_runs(run, env: dict, home: Path, config: Path) -> None:
    work, results, calls = (Path(env["EVAL_WORK_DIR"]), Path(env["EVAL_RESULTS_DIR"]),
                            Path(env["FAKE_CALLS"]))
    good = cases_file(home / "good.json", [
        {"id": "read-java", "fixture": "java", "steps": ["read it", "background"],
         "expect": {"rules_loaded": ["java", "kotlin"], "rules_not_loaded": ["swift", "frontend"],
                    "skills_load": ["java-financial-correctness"],
                    "skills_not_load": ["md2pdf"]},
         "rubric": {"must_find": ["the seeded defect"], "must_not_flag": ["the correct one"]}},
        {"id": "other", "fixture": "java", "steps": ["x"], "repeats": 1}])
    proc = run("run", str(good), "--dry-run", "--repeats", "2")
    check("dry-run: lists every run, the step total and both paths, and writes nothing",
          proc.returncode == 0 and "4 run(s), 6 session step(s)" in proc.stdout
          and str(work.resolve()) in proc.stdout and not work.exists() and not calls.exists(),
          proc.stdout[-400:])
    proc = run("run", str(good), "--dry-run")
    check("dry-run: a case's own repeats wins over the default of 3", "4 run(s)" in proc.stdout,
          proc.stdout[-300:])
    proc = run("run", str(good), "--dry-run", run_env={**env, "EVAL_WORK_DIR": ""})
    check("dry-run: an empty EVAL_WORK_DIR means the default, not the current directory",
          str(home / ".cache" / "claude-config-evals") in proc.stdout, proc.stdout[-300:])
    proc = run("run", str(good), "--dry-run", run_env={**env, "EVAL_WORK_DIR": str(home)})
    check("dry-run: a work dir equal to $HOME is refused before anything else",
          proc.returncode == 2 and "inside $HOME" in proc.stderr, proc.stderr[-300:])
    outside = {**env, "EVAL_WORK_DIR": str(Path(tempfile.gettempdir()) / "eval-outside"),
               "HOME": str(home / "nested-home")}
    proc = run("run", str(good), "--yes", run_env=outside)
    check("run: a work dir outside $HOME is refused",
          proc.returncode == 2 and "inside $HOME" in proc.stderr, proc.stderr[-300:])
    proc = run("run", str(good))
    check("run: without --yes it refuses and starts nothing",
          proc.returncode == 2 and "--yes" in proc.stderr and not calls.exists(),
          proc.stderr[-300:])
    proc = run("run", str(good), "--yes", "--repeats", "0")
    check("run: --repeats below 1 is a usage error", proc.returncode == 2, proc.stderr[-300:])

    proc = run("run", str(good), "--yes", "--case", "read-java", "--repeats", "2",
               "--model", "haiku", "--effort", "low", "--max-budget-usd", "0.5")
    summaries = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    summary = summaries[0] if summaries else {}
    recorded = ([json.loads(line) for line in calls.read_text().splitlines()]
                if calls.exists() else [])
    check("run: succeeds and prints one summary per selected case",
          proc.returncode == 0 and len(summaries) == 1, proc.stderr[-400:])
    first, second = [*recorded, {"argv": []}, {"argv": []}][:2]
    check("run: the first step sets the session id, later steps resume it",
          len(recorded) == 4 and "--session-id" in first["argv"] and "--resume" in second["argv"]
          and first["argv"][first["argv"].index("--session-id") + 1]
          == second["argv"][second["argv"].index("--resume") + 1], json.dumps(recorded[:2]))
    check("run: every parent-session variable is removed and others kept",
          all(c["env"] == {**{name: None for name in PLANTED}, "KEEP_ME": "1"}
              for c in recorded), json.dumps(recorded[:1]))
    check("run: --model, --effort and --max-budget-usd reach the child",
          all({"haiku", "low", "0.5"} <= set(c["argv"]) for c in recorded),
          json.dumps(recorded[:1]))
    check("run: each fixture is written inside the work dir, then removed",
          all(Path(c["cwd"]).parent == work.resolve() for c in recorded)
          and work.exists() and not any(work.iterdir()), json.dumps(recorded[:1]))
    check("run: cost is the session's cumulative total, not a sum over steps or events",
          summary.get("total cost usd") == 0.06 and summary.get("mean cost usd per run") == 0.03,
          json.dumps(summary))
    check("run: tokens come from the cumulative modelUsage, summed over every model",
          summary.get("mean tokens per run", {}).get("outputTokens") == 14 + 2,
          json.dumps(summary.get("mean tokens per run")))
    written = sorted(results.glob("*-test-addition"))
    record = (json.loads((written[0] / "read-java-r1" / "run.json").read_text())
              if written else {})
    check("run: the answer is the last non-empty result, not the first or the empty trailer",
          (record.get("steps") or [{}, {}])[1].get("text") == "final answer",
          json.dumps(record.get("steps")))
    check("run: the case's rubric is stored in each run record for the grader",
          record.get("rubric") == {"must_find": ["the seeded defect"],
                                   "must_not_flag": ["the correct one"]},
          json.dumps(record.get("rubric")))
    main_view = summary.get("contexts", {}).get("main", {}).get("rules", {}).get("java", {})
    sub_view = (summary.get("contexts", {}).get("subagent:code-reviewer", {})
                .get("rules", {}).get("frontend", {}))
    check("run: the summary splits mechanisms per rule and per context",
          main_view.get("runs injected") == 2 and main_view.get("runs native") == 2
          and main_view.get("runs read") == 2 and main_view.get("runs with 2+ copies") == 2
          and sub_view.get("runs native") == 2 and sub_view.get("runs before first file tool") == 0,
          json.dumps(summary.get("contexts")))
    skill_view = summary.get("skills", {}).get("java-financial-correctness", {})
    check("run: the summary splits skill invocations from direct reads",
          skill_view.get("runs invoked") == 2
          and skill_view.get("runs files read after invoke") == 2
          and summary.get("skills", {}).get("md2pdf", {}).get(
              "runs SKILL.md read without invoke") == 2, json.dumps(summary.get("skills")))
    check("run: unmet expectations are listed, met ones are not",
          summary.get("unmet") == ["skill md2pdf not loaded: loaded in 2/2"],
          json.dumps(summary.get("unmet")))
    check("run: results land under EVAL_RESULTS_DIR with run records and streams",
          len(written) == 1 and (written[0] / "read-java-r2" / "step-1.jsonl").is_file()
          and (written[0] / "summary.json").is_file(), str(written))

    (written[0] / "summary.json").unlink()
    stale = json.loads((written[0] / "read-java-r1" / "run.json").read_text())
    stale["steps"][1]["cumulative_cost_usd"] = 99
    stale["analysis"] = {"stale": True}
    (written[0] / "read-java-r1" / "run.json").write_text(json.dumps(stale))
    proc = run("report", str(written[0]))
    regenerated = json.loads(proc.stdout.splitlines()[0]) if proc.returncode == 0 else {}
    check("report: recomputes records and the summary from the streams and transcripts",
          proc.returncode == 0 and regenerated.get("total cost usd") == 0.06
          and regenerated.get("contexts") == summary.get("contexts")
          and (written[0] / "summary.json").is_file(), proc.stderr[-300:])
    proc = run("report", str(home))
    check("report: a directory with no run records exits 2", proc.returncode == 2,
          proc.stderr[-300:])

    kept_analysis = json.loads((written[0] / "read-java-r1" / "run.json").read_text())
    for transcript in (config / "projects" / "fake").glob(
            f"{kept_analysis['session_id']}.jsonl"):
        transcript.unlink()
    (written[0] / "read-java-r2" / "step-1.jsonl").unlink()
    proc = run("report", str(written[0]))
    after = json.loads((written[0] / "read-java-r1" / "run.json").read_text())
    second_run = json.loads((written[0] / "read-java-r2" / "run.json").read_text())
    check("report: a run whose transcript is gone keeps its stored analysis, marked so",
          proc.returncode == 0 and after.get("analysis") == kept_analysis.get("analysis")
          and after.get("analysis_source") == "original run" and after.get("failed") is False,
          json.dumps({k: after.get(k) for k in ("analysis_source", "failed", "error")}))
    check("report: a step whose stream is gone keeps its stored values",
          second_run["steps"][1].get("text") == "final answer"
          and second_run["steps"][1].get("cumulative_cost_usd") == 0.03,
          json.dumps(second_run["steps"][1]))
    broken = home / "broken-results" / "case-r1"
    broken.mkdir(parents=True)
    (broken / "run.json").write_text("{not json", encoding="utf-8")
    proc = run("report", str(broken.parent))
    check("report: a malformed run record exits 2 without a traceback",
          proc.returncode == 2 and "not a run record" in proc.stderr
          and "Traceback" not in proc.stderr, proc.stderr[-300:])

    soft = cases_file(home / "soft.json", [
        {"id": "soft", "fixture": "java", "steps": ["soft-error", "never sent"], "repeats": 1}])
    before = len(calls.read_text().splitlines())
    proc = run("run", str(soft), "--yes")
    sent = len(calls.read_text().splitlines()) - before
    check("run: an error result with exit 0 fails the run and stops its steps",
          proc.returncode == 1 and sent == 1
          and json.loads(proc.stdout.splitlines()[0]).get("failed") == 1, proc.stderr[-300:])
    mixed = cases_file(home / "mixed.json", [
        {"id": "mixed", "fixture": "java", "steps": ["error-then-ok"], "repeats": 1}])
    proc = run("run", str(mixed), "--yes")
    check("run: an error result followed by a success still fails the run",
          proc.returncode == 1 and json.loads(proc.stdout.splitlines()[0]).get("failed") == 1,
          proc.stderr[-300:])
    failing = cases_file(home / "failing.json", [
        {"id": "broken", "fixture": "java", "steps": ["fail"], "repeats": 1,
         "expect": {"rules_loaded": ["java"]}}])
    proc = run("run", str(failing), "--yes")
    broken_summary = json.loads(proc.stdout.splitlines()[0]) if proc.stdout.strip() else {}
    check("run: a failing exit status fails the run and exits 1", proc.returncode == 1,
          proc.stderr[-300:])
    check("run: a run without analysis is counted apart, not judged as unmet",
          broken_summary.get("runs without analysis") == 1 and broken_summary.get("unmet") == [],
          json.dumps(broken_summary))
    broken_record = next(results.glob("*/broken-r1/run.json"))
    first_error = json.loads(broken_record.read_text()).get("error") or ""
    run("report", str(broken_record.parent.parent))
    check("report: a run with no analysis keeps its stored error text",
          first_error.startswith("no transcript")
          and json.loads(broken_record.read_text()).get("error") == first_error, first_error)
    violated = cases_file(home / "violated.json", [
        {"id": "violated", "fixture": "java", "steps": ["x"], "repeats": 1,
         "expect": {"rules_not_loaded": ["java"]}}])
    proc = run("run", str(violated), "--yes")
    violated_summary = json.loads(proc.stdout.splitlines()[0]) if proc.stdout.strip() else {}
    check("run: a rule that should stay out but loaded is listed as unmet",
          proc.returncode == 0
          and violated_summary.get("unmet") == ["rule java not loaded in main: loaded in 1/1"],
          json.dumps(violated_summary.get("unmet")))
    keep = cases_file(home / "keep.json", [
        {"id": "kept", "fixture": "java", "steps": ["x"], "repeats": 1}])
    proc = run("run", str(keep), "--yes", "--keep")
    kept = [path for path in work.iterdir() if "kept" in path.name]
    check("run: --keep leaves the fixture copy in place",
          proc.returncode == 0 and len(kept) == 1 and (kept[0] / "pom.xml").is_file(),
          str(list(work.iterdir())))

    probe = subprocess.run([sys.executable, "-c", (
        "import importlib.util, sys; from pathlib import Path; "
        "spec = importlib.util.spec_from_file_location('candidate', sys.argv[1]); "
        "e = importlib.util.module_from_spec(spec); spec.loader.exec_module(e); "
        "e.remove_run_dir(Path(sys.argv[2]), Path(sys.argv[3]))"),
        EVAL_CONFIG, str(home / "keep.json"), str(work)],
        env=env, capture_output=True, text=True, timeout=60, check=False)
    check("run: deletion refuses a path outside the work dir",
          probe.returncode != 0 and "refusing to delete" in probe.stderr
          and (home / "keep.json").exists(), probe.stderr[-300:])

    proc = run("scan", "--summary")
    totals = json.loads(proc.stdout) if proc.returncode == 0 else {}
    java_totals = totals.get("rules", {}).get("java", {})
    check("scan: eval and config-dir sessions are left out by default",
          totals.get("sessions") == 3, proc.stdout[-400:])
    check("scan: counts injections, duplicates, excess characters, reads and subagent loads",
          java_totals.get("sessions injected") == 1
          and java_totals.get("sessions with 2+ copies") == 1
          and java_totals.get("excess chars") == len(JAVA_2)
          and java_totals.get("sessions read in main") == 1
          and totals.get("rules", {}).get("frontend", {}).get(
              "native loads in subagent:code-reviewer") == 1, json.dumps(totals.get("rules")))
    check("scan: skill metrics are split the same way",
          totals.get("skills", {}).get("md2pdf", {}).get(
              "sessions skill_md_read_without_invoke") == 1, json.dumps(totals.get("skills")))
    proc = run("scan", "--summary", "--include-config")
    check("scan: --include-config keeps sessions run inside the config directory",
          json.loads(proc.stdout).get("sessions") == 4, proc.stdout[-300:])
    eval_sessions = len(list((config / "projects" / "fake").glob("*.jsonl")))
    proc = run("scan", "--summary", "--include-evals")
    check("scan: --include-evals keeps the harness's own sessions",
          eval_sessions >= 5 and json.loads(proc.stdout).get("sessions") == 3 + eval_sessions,
          f"{eval_sessions} eval transcripts; {proc.stdout[-300:]}")
    proc = run("scan", "--since", "2999-01-01")
    check("scan: --since filters by session start",
          proc.returncode == 0 and proc.stdout.strip() == "", proc.stdout[-300:])


def test_eval_config() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        config = home / ".claude"
        fake = home / "fake-claude"
        fake.write_text(FAKE_CLAUDE.format(python=sys.executable), encoding="utf-8")
        fake.chmod(0o755)
        template = home / "template.jsonl"
        write_jsonl(template, [injection("r0", JAVA_1), injection("r5", FRONTEND_POINTER),
                               tool("Skill", {"skill": "java-financial-correctness"}),
                               tool("Read", {"file_path": str(config / "skills"
                                                              / "java-financial-correctness"
                                                              / "SKILL.md")}),
                               tool("Read", {"file_path": str(config / "skills" / "md2pdf"
                                                              / "SKILL.md")}),
                               native("r4", config / "rules" / "java.md", "j" * 30),
                               tool("Read", {"file_path": str(config / "conventions"
                                                              / "java.md")}, "tr"),
                               result("tr", "r6", "1\t# Java conventions\n"),
                               tool("Bash", {"command": "cat ~/.claude/conventions/kotlin.md"},
                                    "tk"),
                               result("tk", "r7", "# Kotlin conventions\n")])
        subagent = home / "subagent.jsonl"
        write_jsonl(subagent, subagent_transcript(config))
        env = {**os.environ, "HOME": str(home), "CLAUDE_CONFIG_DIR": str(config),
               "CLAUDE_BIN": str(fake), "EVAL_WORK_DIR": str(home / "evals-work"),
               "EVAL_RESULTS_DIR": str(home / "evals-results"),
               "FAKE_CALLS": str(home / "calls.jsonl"), "FAKE_STATE": str(home / "state"),
               "FAKE_TRANSCRIPT": str(template), "FAKE_SUBAGENT": str(subagent),
               "FAKE_PLANTED": json.dumps(sorted(PLANTED)), **PLANTED}

        def run(*args: str, run_env: dict = env) -> subprocess.CompletedProcess:
            return subprocess.run([sys.executable, EVAL_CONFIG, *args], env=run_env,
                                  capture_output=True, text=True, timeout=120, check=False)

        proc = run("--help")
        check("help: exits 0 and documents every command",
              proc.returncode == 0 and all(word in proc.stdout for word in
                                           ("run CASES", "report RESULTS", "analyze SESSION",
                                            "scan")), proc.stdout[-300:])
        test_analysis(run, config)
        test_case_validation(run, home)
        test_runs(run, env, home, config)


def main() -> int:
    test_eval_config()
    for failure in _failures:
        print(f"FAIL {failure}")
    print(f"{_passes} passed, {len(_failures)} failed")
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
