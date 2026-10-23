# Maintainer notes

This file exists so a future maintainer can see why the setup is shaped the way it is.
Nothing loads it on its own. `AGENTS.md` beside it points here, and Claude Code reads that
pointer in any session under the home directory whose project has no `CLAUDE.md` of its own
(`~/.claude/CLAUDE.md` does not count). Read this file before any change `git status` would
show in this repo, an edit or a new file (2026-10-11; see the decision log).

## Agents in this setup

| Agent | Role | Invoked by |
|---|---|---|
| `code-reviewer` | Staff-level review of a diff: design, correctness, operability, code-level. Severity-tagged 🔴/🟡/🔵, verdict ✅/⚠️/🔴. | The user directly, or a session running the self-review loop in a body in `conventions/`. |
| `learning-doc-writer` | Pandoc-ready learning documents, with a mandatory independent adversarial review before hand-back. | The user directly, or auto-routed on its description. |

Both are `model: inherit`. The one deliberate exception is inside
`learning-doc-writer`: its fetch-only source-gathering spawns pass `sonnet`, because a
gatherer opens an already-identified source and reports what it says. Judgment spawns
never take the flag (decided 2026-08-13).

## Reviewer memory protocol

`memory: user` is set on both agents, so Claude Code injects the generic memory
instructions and the `MEMORY.md` index itself. Only the setup-specific half lives in
`agents/code-reviewer.md` § Memory protocol, and it is this:

- Prompt carries `Invocation: self-review loop`, or context otherwise shows an agent
  drove the invocation → **never save**. End with a **Proposed memory** note; the
  invoking session relays it verbatim and records it only on the user's approval.
- Direct user invocation with explicit feedback → the reviewer saves it itself.
- Ambiguous → fail closed, propose.

The reason is narrow and worth keeping: in a loop the only validator present is another
model, and architect pushback must not be laundered into reviewer calibration without a
human seeing it. Writes are confined to `agent-memory/code-reviewer/` and scratch — never
the repo, never config, never through `Bash` redirects — and since 2026-09-24
`hooks/reviewer-guard.py` enforces that rather than trusting the prompt with it.

Edge cases: a ⚠️ verdict carrying only 🔵 issues may return to the user unchanged, since
🔵 is judged on merit. A failed reviewer spawn falls back to a structured self-review and
says explicitly that the external reviewer was skipped — no retry loop.

## Decision log

- **Python is the fourth rule** (2026-10-23, Phase 2 of the language-rules plan). Its body is
  `conventions/python.md`, its stub `rules/python.md`. The observation window starts at this
  change's commit and runs 21 days or 5 sessions in Python repos, whichever is later.
  - **Detection** looks only at the session's directory and its git toplevel, never below:
    `pyproject.toml`, `setup.py`, `setup.cfg`, `requirements.txt` or `uv.lock`. A Python tool
    nested in another repo therefore does not count. Across the owner's repos, the two
    Python projects match, and PersonalFinance's `deploy/…/requirements.txt` does not. No
    Java, React or Swift repo has a Python marker at its top. A session started inside the
    nested tool's own directory does get the body, since that directory is its top.
  - **Loading, measured on CLI 2.1.309 with haiku at low effort, three runs per case.** The
    baseline ran before go-live and loaded no Python text anywhere.
    - Every positive case got the body in 3 of 3 runs, injected before the first file tool:
      a plan with no tool, a Read, a `cat`, a repo marked only by `requirements.txt`, and a
      mixed root with `pom.xml` and `pyproject.toml`, which got the Java body too.
    - Every negative case got no Python body: Java, React, and the PersonalFinance-shaped
      fixture, where a nested `.py` loaded the 214-character stub alone.
    - No context held a body twice or two stubs.
    - A local clone of the owner's Python repo got one injected body, 7,387 characters with
      its header, and one stub after a Read and an Edit. A clone of PersonalFinance got the
      Java and React bodies, and only the Python stub when its relay script was read.
    - The haiku reviewer read the body in 2 of 3 runs. In the third it read the file through
      `git status && cat -n`, which loads nothing natively, and skipped its lens's read. On
      the daily model, opus at xhigh, it read the body in 3 of 3 runs, once only through a
      `grep` for its money rules.
  - **The review eval.** The fixture seeds five defects: a naive `datetime.now()` that
    crashes on the cache's aware timestamp, `Decimal(0.0075)`, a bare `except` that drops
    rows, `shell=True` with an interpolated path, and an unannotated function. Opus at
    xhigh ran three reviews per condition, and a subagent graded all six blind, with the
    body's Stack and Verification sections:
    - baseline: 15 of 15 seeded defects found, 31 other useful findings, 7 false positives;
    - treatment: 15 of 15, 44 and 9.

    The fixture sits at the model's ceiling, as Swift's did, so "found more often" cannot
    show. The rule added 8 useful findings about the code (36 against 28) and 5 about
    tooling (8 against 3), such as the missing `uv.lock`. Three of the treatment's false
    positives ask for the CHF conversion's rounding to move into a named function, which
    the body's Money section requires and the grader did not see. Counted against the
    rule, the treatment has 6 false positives to the baseline's 7. Two more call
    `page_count`'s `ValueError` a failure that needs its own class, an over-reading of the
    body's exception-class line. Both conditions shared one false positive three times: a
    cwd-relative `--rates` default.

    The first round's five results directories hold $7.18 of runs: $4.69 for the two
    review conditions, $2.03 for three daily-model reviewer runs, and $0.46 for the haiku
    loading cases. The two clone probes cost $0.02 more. The treatment's `grading/`
    directory keeps the grader's input, key and grades.
  - **The hook tests** gained detection rows for each marker, a nested `pyproject.toml`, a
    directory named `pyproject.toml`, a `src/` subdirectory under a git toplevel, and a
    PersonalFinance-shaped repo from its root, its frontend and its nested tool. A copy of
    the hook that detects at depth 2 fails the three nested rows. A copy without the
    `python` row fails 17: the 16 Python rows, and validate-rules on the live body.
  - **Also changed.** The reviewer has a Python lens that reads the body. Its script lens
    sends a Python script to the body's ruff and mypy commands. Bare `uvx ruff check` lacks
    the rule set, and bare `uvx mypy` lacks the script's dependencies and checks against
    uvx's own Python: it passed a 3.14 script that imports `cgi`, which 3.13 removed.
    `CLAUDE.md`'s test markers name pytest and Swift Testing, with `#` comments in Python.
    The body says that code tied to another interpreter, such as this repo's hooks and
    scripts on `/usr/bin/python3` 3.9, keeps that floor: the stub's `**/*.py` loads in
    `~/.claude` too.
  - **The first review corrected three facts the probes had missed.** pydantic's float path
    for JSON numbers: the probe used numbers too short to show it. mypy's Python version for
    a script: the probe script used no new API. And `check=False` is right where the exit
    status is data. The body and the lens now say each. The second review found the script
    lens still sending scripts without dependencies to bare `uvx mypy`. The lens's `uv.lock`
    finding also follows the body's exception for code tied to another interpreter. The
    review eval ran on the body before these fixes, and none of them touches a seeded
    defect.
  - **Revised the same day on the owner's two answers.** Existing projects get no legacy
    clause, and exception design follows the best practice for a professional project or
    a published script.
    - The body no longer says "from scratch". An existing project moves onto the stack in
      a change of its own, never inside a fix or a feature, and each session in a project
      not yet moved proposes it once. The end state stays strict. Only the order is set,
      so a one-line fix does not start a migration nobody asked for.
    - Until the move, a change follows the code rules the project's Python supports,
      writes tests for the project's runner, adds dependencies with the project's
      tooling, and passes the project's own checks. Verification's step 1 names those
      checks off the stack. The lens says they replace the `uv run --locked` ones, and it
      rates a fix or a feature that adds `uv.lock` or the body's configuration to an
      unmoved project 🟡: that change has started the move inside it. A `dev` group alone
      does not count: in a uv project with a lock and no configuration, a first test's
      `uv add --dev pytest` adds one, and the body allows that change.
      - In a project with no lock, `uv run --locked ruff check` exited 1 and created a
        `.venv`, and its error hint points at `uv lock`, which would start the move inside
        the fix.
      - `uv add packaging` in a setuptools project with a `requirements.txt` exited 0. It
        wrote `uv.lock` and an egg-info, added the dependency to `pyproject.toml` only, and
        left `requirements.txt` without it.
      - `python -m unittest discover` ran none of a plain failing `def test_…`: "Ran 0
        tests", exit 0 and "OK" on 3.9, exit 5 on 3.13. Hence the project's runner.
    - The script form of `ruff check` was tried as an interim check and dropped. On a
      test that follows the rule it raised S101, which the project block ignores for
      `tests/` and the script command does not. With no `requires-python`, it inferred no
      target and raised UP045, whose `int | None` fix fails at import on 3.9. On legacy
      files it gave findings with no pass criterion short of cleaning the whole file,
      which would put behaviour fixes inside the fix.
    - The move is a series of commits: the project's code renamed under `src/` alone,
      tooling and lock, the formatter's pass alone, then the fixes, one concern per
      commit. It lands once the owner agrees and every check passes. Many ruff fixes
      change behaviour (DTZ, BLE, TRY, B), and one commit for all of them could only be
      reverted whole. A rename on its own keeps `git log --follow` and blame. A build
      backend that reads `[project]` may stay. The Python version is the project's own,
      3.11 at least, and an older one upgrades first, in a change of its own.
    - The floor of 3.11 is the body's own code. Python 3.11's What's New lists
      `enum.StrEnum`, `datetime.UTC` and `typing.assert_never` as added there, and Data
      and Time name all three. The devguide lists 3.10 as end of life since 2026-10-01,
      and 3.11's end of life is scheduled for 2027-10, so revisit the floor then.
      - pytest 9 needs 3.10 and would set a lower floor. At `requires-python >=3.9`,
        `uv add --dev ruff mypy pytest` forked the lock to pytest 8.4.2 and mypy 1.19.1
        below 3.10. On 3.9, pytest 8.4.2 ignored the body's `[tool.pytest] strict = true`
        and passed a misspelled marker with a warning, exit 0.
      - The body's `"pytest>=9"` refused 3.9 instead ("pytest>=9.0.0 depends on
        Python>=3.10"). On a new 3.15 project it wrote `pytest>=9` with mypy 2.4.0 and
        ruff 0.17.2.
    - The lens rates a missing `uv.lock` or configuration 🟡 only on a diff that creates
      the project or is its move. On any other diff it names the move in its Summary and
      leaves it out of the verdict, since the self-review loop could otherwise not end
      without doing the move inside it. Code tied to another interpreter is exempt.
    - The move's commands were run on scratch projects:
      - Plain `uv init --package --name feeds` beside an existing `src/feeds/` left the
        code alone and added a `[project.scripts]` entry for a `main` the code lacked.
        Over a flat `feeds/`, it added uv's template as a second `src/feeds/__init__.py`:
        `uv run --locked feeds` printed "Hello from feeds!" and exited 0, and `import feeds`
        from the project root found the old copy.
      - `uv init --bare --package` wrote only `pyproject.toml`, with no entry point.
        `uv sync` then failed on the flat layout ("Expected a Python module at:
        src/feeds/__init__.py") and passed once the code moved under `src/`.
        `uv python pin` wrote `.python-version`, which `--bare` leaves out.
      - `uv add -r requirements.in -c requirements.txt` kept a pip-tools pin at requests
        2.31.0. `uv add -r` on a fully pinned file, the shape `pip freeze` writes, made
        all five packages direct `==` dependencies, so a frozen file is a constraint, not
        a source.
      - With a `poetry.lock` pinning 2.31.0, `uv sync` installed 2.34.2 and nothing of
        Poetry's dev group. On a Poetry 1.x file with no `[project]` table, `uv sync`
        exited 0, locked neither the project nor requests, and `import requests` failed.
        `uvx migrate-to-uv --keep-current-build-backend` (0.12.0) converted both formats
        and kept 2.31.0 from the lockfile under a `>=2.31,<3` range. On a pip-tools
        project that already had an empty `[project]`, it kept `dependencies = []`,
        deleted both requirements files and exited 0, so the body names it for Poetry
        only. uv's own migration guides cover pip only.
    - A copy of the owner's Python project without `uv.lock`, 42 files and 3,554 lines,
      took `uv add --dev` and the configuration block. Its checks then reported 313 ruff
      findings, 39 files to reformat and 298 mypy errors, which is why the move is a
      change of its own.
    - Exceptions follow PEP 8, which designs hierarchies "based on the distinctions that
      code catching the exceptions is likely to need": one base per package or script, a
      subclass only where a caller handles a failure apart, and `ValueError` or
      `TypeError` for a bad argument, as the built-in exceptions page defines them. Bad
      data is defined by where it comes from (a file, a process, the network, the user),
      even when it arrives as an argument, so a parser of user text has one answer. The
      entry point catches the base with `sys.exit(f"error: {error}")`. The `sys` docs say
      a string argument is printed to stderr with exit status 1, and the probe printed one
      line with no traceback. TRY400
      rejected `logger.error` inside an `except`, `exc_info=False` included, and the
      reviewer found that ruff's suggested `exc_info=False` with `logger.exception` trips
      TRY401. The pattern passed the body's ruff, mypy and pytest configuration. TRY003
      stays ignored for a sharper reason: it wants a class per message. The lens rates
      exception design 🔵.
    - The first eval's two "`page_count`'s `ValueError`" false positives now ask for what
      the rule requires: `pdfinfo` output with no page count is bad data from a process,
      not a bad argument, so it raises the package's base class.
    - A second treatment review eval ran on the revised body, before this revision's
      review fixes, in `20261023T120851Z` for $2.40. A fresh grader scored it blind beside
      the same three baseline answers, given the revised Stack and Verification sections:
      - baseline: 15 of 15 seeded defects, 39 other useful findings, 1 false positive;
      - treatment: 15 of 15, 47 and 8.

      Like for like, the first round's grader gave the same baseline answers 31 and 7, so
      the grader varies, as Swift's did. The treatment's useful findings are 39 about the
      code and 8 about tooling, against the baseline's 36 and 3. Six of its 8 false
      positives ask for what the body requires and the grader did not see: three name
      `page_count`'s `ValueError`, three the CHF conversion's inline rounding. Counted
      against the rule, the treatment has 2 false positives to the baseline's 1: an
      unrounded balance column, and a remark that `ROUND_HALF_EVEN` is unusual, which the
      rubric lists as must not flag. All three treatment answers asked for a package base
      exception. The rerun brings this phase's results directories to $9.58.
  - **Revised a third time, on an outside review the owner accepted.** The move's
    procedure left the body for the `python-migration` skill. The body keeps the policy:
    a change of its own, proposed once per project, and a refusal or deferral kept in the
    project's memory until the project changes materially. The sub-bullets above describe
    the procedure's content, which now lives in the skill.
    - The outside review corrected four facts. Each was checked:
      - TRY003 does not ask for a class per message. ruff's own example passes the value
        to one class that builds the message. The rule stays off because each raise site
        states its own message.
      - Expected failures and contract violations now decide the exception class, not
        where the data came from.
      - "Full precision" was false. `Decimal` computes to its context, 28 significant
        digits by default (`1/3` gave 28 threes), so the body asks for one stated context.
        The rounding unit follows the currency and the operation: CLDR, through Babel,
        gives 2 decimals for CHF, 0 for JPY and 3 for BHD.
      - A script's lockfile does not pin its checkers. `uvx ruff@0.17.2` and
        `uvx mypy@2.4.0` ran, and the body's script commands now pin both.
    - Smaller changes:
      - Structure scales with the change.
      - Subprocess capture depends on the output.
      - A domain dataclass is required only where it holds invariants.
      - `Literal` is allowed for a closed set. mypy named the missing member when a
        `match` over a `Literal` ended in `assert_never`.
      - A script whose logic needs tests against its dependencies becomes a project.
    - The skill's checks were run. With setuptools, a `src/` package that reads a JSON
      resource built and installed cleanly, then failed with `FileNotFoundError`. Naming
      the file in `[tool.setuptools.package-data]` fixed it. uv_build shipped the file.
      `uv export --format requirements.txt --no-dev` wrote the five runtime pins and no
      pytest, plus an `-e .` line that pip refuses beside hashes; `--no-emit-project`
      drops it. The CI and Docker lines follow uv's own guides. `uv venv` refuses a
      directory that already has an environment, so the clean install uses `mktemp -d`.
    - Selection, haiku at low effort, three runs each (`20261023T140007Z`, $0.05): the
      skill loaded in 3 of 3 runs once the owner agreed to the move, and in 0 of 3 for a
      fix in the same unmoved fixture. This phase's results directories now hold $9.63.
    - The owner capped the review at one pass. It found six 🟡, each reproduced or probed,
      and all applied without a second review:
      - `quantize` keeps only the exponent of its unit, so a 0.05 step left 12.33 as is;
      - the script pins had no stated version source;
      - a leftover `ruff.toml` turned a failing check into a pass;
      - `-e .` in the export;
      - no branch for a `setup.py`-only project;
      - no branch for a single script with a `requirements.txt`, whose pins survive only
        when the lock comes before `uv add -c`.

      The remaining 🔵 are listed in the hand-back.
    - Not taken: putting the calibration tiers first. They sit in the self-review loop
      text, which stays identical across bodies. The intro's scaling sentence does that
      job. Narrowing "facts come from documentation" was also not taken, as the owner's
      principle.
  - **Facts were fetched and run, 2026-10-23.** Each was checked on a scratch uv project and
    a PEP 723 script, on CPython 3.15.0:
    - CPython 3.15.1 is the current stable release (python.org). pydantic 2.14.1 installs
      on 3.15: its compiled half, pydantic-core 2.50.1, ships cp315 wheels.
    - uv 0.13.5. `uv init --package` gives a `src/` layout, the `uv_build` backend and
      `.python-version`. The `dev` group syncs by default. A plain `uv run` rewrote a stale
      `uv.lock` without saying so, and `uv run --locked` refused it. `uvx mypy` in the
      project failed to import pydantic. `--with-requirements` takes a PEP 723 script but
      ignores its lockfile: with pydantic locked at 2.10.5, it installed 2.14.1.
      `uv sync --locked --script` built the script's own environment at 2.10.5 and refused
      a stale lockfile, and `uv python find --script` names that environment's
      interpreter. mypy's `--python-executable` takes only that interpreter's packages:
      mypy checks against the Python it runs on, and uvx ran it on uv's managed 3.12. A
      valid 3.14 script failed on `itertools.batched(strict=True)` until
      `--python-version` named its floor.
    - ruff 0.17.2. Since 0.16.0 (2026-07-23) the default set has 413 rules, up from 59, and
      0.17.0 dropped several DTZ rules from it. `select` replaces that set, so the rule
      uses `extend-select`. S603 flagged every subprocess call, a literal absolute path
      included, so it is ignored. TRY003 flagged an inline f-string message, and a `msg`
      variable silenced it, so it is ignored too. S607 flagged a bare executable name, and
      a `shutil.which` result passed. RUF032 flagged `Decimal(0.0075)` but not a float
      variable. `contextlib.suppress(Exception)` passed ruff, BLE included, so the rule
      bans it by name. `except Exception` with `logger.exception` and a non-zero return
      passed BLE001.
    - mypy 2.4.0, with `strict = true`, `warn_unreachable` and pydantic's plugin. mypy
      2.0 turned on `--local-partial-types` and `--strict-bytes` by default, and 2.4 made
      the native parser the default. `assert_never` named the enum member a `match`
      missed. An unannotated function failed; a `cast` of `Any` passed, so its reason is a
      convention no tool checks.
    - pytest 9.1.1. 9.0 added native TOML under `[tool.pytest]` and `strict = true`, which
      turns on future strictness options too. The lock pins pytest, so that is safe.
    - pydantic reads a JSON number into a `Decimal` field through a float:
      `0.123456789012345678` became `0.12345678901234568`, and `1234.50` became `1234.5`.
      A JSON string, and `json.loads(…, parse_float=Decimal)` followed by `model_validate`,
      kept every digit.
  - **mypy over pyright and ty.** pyright from PyPI runs on Node.js, which it finds or
    downloads. ty 0.0.91 is in beta and says its diagnostics may change between any two
    versions. mypy is the reference checker and the one pydantic ships a plugin for.
    Revisit when ty leaves beta.
  - **Rejected:**
    - Detection at depth 2, like the other rules. It would give PersonalFinance the body
      for one relay script.
    - `select` with an explicit list. It would drop most of ruff's curated defaults.
    - A `msg = …` variable before each `raise` to satisfy TRY003.
    - A legacy clause that keeps an existing project's pip, Poetry or setuptools-only
      tooling. The owner chose strict.
    - `logger.error` for an expected failure at the entry point. TRY400 rejects it, and
      ignoring TRY400 would let any handler drop a traceback.
    - One exception class per raise site. PEP 8 asks for the distinctions callers need.
    - A move that lands green behind a baseline (`ruff check --add-noqa`, per-module
      `ignore_errors` in mypy), as mypy's guide for existing code suggests. It would leave
      the strict end state as debt in the code. The series of commits reaches it instead.
    - "No other change lands before the move". It would block a fix the owner wants now.

- **The rule bodies moved to `conventions/`, each `rules/` file is now a stub, and Swift is
  the third rule** (2026-10-22, Phase 1 of the language-rules plan). The Swift rule's
  observation window starts at this change's commit. It runs 21 days or 5 sessions in Swift
  repos, whichever is later.
  - **The mechanism.** `session-rules.sh` injects bodies from `conventions/`. One table gives
    each rule its label, markers, search depth and a veto. `validate-rules.sh` checks every
    body against the real hook from one fixture table. It also compares the self-review
    loops across all bodies and checks each stub. The reviewer's Java, frontend and Swift
    lenses read their body explicitly. The Java body lost its note on the contract globs.
    A YAML comment in the stub's frontmatter carries it now, beside the globs it explains.
  - **Loading, measured on CLI 2.1.308 with haiku at low effort.** Phase 0's matrix ran once
    per case, and the Swift cases three times each:
    - No context held a body twice or two stubs. Every main-context body came from the
      injection, before the first file tool.
    - A stub is 227 characters for Java, 286 for frontend and 271 for Swift. A body is 8.4k
      to 9.5k. The loading runs used the first Swift body, at 5.2k.
    - Angular's `.ts`, `.scss` and `tailwind.config.js` now load nothing. The frontend stub
      dropped `.ts`, `.js`, `.mjs`, `.css` and `.scss`, as planned, and `tailwind.config.*`
      too, because Angular repos use Tailwind.
    - In React Native, `App.tsx` loads the frontend stub and `ios/*.swift` the Swift stub.
      No run read either body. **Accepted:** a stub costs under 300 characters and says
      the rule does not apply there.
    - A `cat` of two files, a piped `cat`, and a compound `git status && cat -n f` still load
      nothing natively.
    - Tetris got one injected body (5,405 characters) and one stub after a Read and an
      Edit. The probe ran in a local clone, which has no `.xcodeproj`, since Tetris
      gitignores it. A mixed Java and XcodeGen repo got one body and one stub per rule.
  - **The reviewer reads its body.** At haiku and low effort, the Swift reviewer read it in
    1 of 3 runs, and no stub reached it, because it read files through compound commands.
    On the daily model, opus at xhigh, it read the body in 3 of 3 Swift runs and in 3 of 3
    Java runs. Each time, that read was the reviewer's only copy, beside its stub.
  - **Swift detection** finds `Package.swift`, a `*.xcodeproj` or `*.xcworkspace`
    directory, or an XcodeGen `project.yml` at depth 2 or less. The `project.yml` counts
    only when a target in its top-level `targets:` declares `type:` and an Apple `platform:`
    or `supportedDestinations:` among its own keys. awk reads this, because the hook
    already depends on nothing more. A repo whose root `package.json` depends on
    `react-native` is vetoed, from the session's directory or its git toplevel.
    `node_modules`, `.build`, `Pods` and `DerivedData` do not count. `test_hooks.py` checks
    that `settings.json` runs the hook for every body. No Stop hook runs that suite, so the
    check holds only where a change runs it, as each phase of the plan does.
    **Accepted gap:** other cross-platform shells still get the Swift body: a React Native
    app in a monorepo's subdirectory, Flutter's `ios/Runner.xcodeproj`, Capacitor's
    `ios/App`. None of the owner's repos has one. Revisit when one appears.
  - **The Swift review eval.** The fixture seeds four defects: a non-`Sendable` shared class,
    a force unwrap, a UI mutation off the main actor, and an XCTest unit test. Opus at xhigh
    ran three reviews per condition, and a subagent graded them blind against the rubric:
    - baseline: 11 of 12 seeded defects found, 42 other useful findings, 5 false positives;
    - treatment: 12 of 12, 59 and 5.

    The model finds these defects without the rule, so this fixture sits at its ceiling.
    The measured effect is more useful findings for the same false positives. "Found more
    often" holds by one finding, and the grader marked that call borderline. Every answer
    in both conditions flagged a `best!` in a Swift Testing test, which the rubric listed as
    must not flag. Since `try #require` exists for this, the advice may be right, and the
    rubric item is the owner's call.

    After the revision below, and before its review fixes, three more treatment reviews ran,
    and a fresh grader scored them blind beside the same three baseline answers, without
    the dropped rubric item:
    - baseline: 11 of 12 seeded defects, 34 other useful findings, 12 false positives;
    - treatment: 12 of 12, 41 and 30.

    15 of the treatment's 30 false positives are what the revised rule requires and the
    fixture lacks: approachable concurrency, `minimumXcodeGenVersion`, the package's
    `swiftSettings`, `performAccessibilityAudit()`, a README with the Xcode version, and a
    gitignored `.xcodeproj`. The grader had no conventions file. Counted against the
    rule, the treatment has 56 useful findings and 15 false positives. The rest are
    mostly the same taste calls in both conditions: bounds checks, magic numbers,
    `@testable`. The grader varies: like for like, the same baseline answers scored 45
    useful findings and 2 false positives in the first round, 34 and 12 in the second.
    So "no more false positives" holds only within that noise, and only with the rule's
    own requirements counted as findings.

    This phase's results directories hold $11.59 of runs: $11.16 for the opus reviews and
    reviewer runs, and $0.43 for the haiku loading cases, each rounded to the cent. The
    Tetris probe, which has no results directory, cost $0.01 more. Each treatment run
    keeps its grader's input, key and grades in its `grading/` directory.
  - **Facts were fetched.** The Swift rule's settings, APIs and commands were checked
    against swift.org, Apple's documentation, SE-0461, SE-0466 and SE-0480, the swift-format
    README, XcodeGen's ProjectSpec, and the installed Xcode 27 and Swift 6.4. No official
    source discourages `DispatchQueue`. Its ban is the owner's convention, and the rule cites
    none.
  - **Revised after an independent review** (2026-10-23). The owner had another agent review
    the Swift rule, and asked for six changes and for `!` to be banned in tests:
    - Each project records its tool versions and OS floors. Apple has no official way to pin
      Xcode, so its version goes in the README. `.xcode-version` was rejected: it serves a
      third-party tool. XcodeGen enforces `options.minimumXcodeGenVersion`: 2.46 refuses a
      spec asking for 99.0.0.
    - The compiler, the language mode and the concurrency settings are separate items.
      **Decided:** `NonisolatedNonsendingByDefault` is on in app and core alike, through
      `SWIFT_APPROACHABLE_CONCURRENCY` in app targets and `.enableUpcomingFeature` in the
      package. Tetris's app target already turns it on, Swift 6.4 lists it as a default of
      language mode 7, and it gives a plain `nonisolated` async function one meaning
      across app and core. A probe confirmed it through a manifest: with it on, a
      `nonisolated` async function ran on its caller's actor; off, and with the name
      misspelled, it ran on the generic executor. A misspelled feature name is ignored
      without a warning, and the rule says so.
    - `xcodegen generate` runs before every build, so added, removed or moved files cannot
      leave the project stale.
    - Concurrency covers actor reentrancy (SE-0306), stale async results, and who owns a
      `Task { }`. A probe showed an `async let` child cancelled with its parent, and a
      `Task { }` made inside that parent not cancelled. The first draft offered
      `.task(id:)` as enough against a stale result. The review's probe showed otherwise:
      cancellation is cooperative, and a cancelled task that does not throw still wrote the
      old query's result last. The rule now requires a check of `Task.isCancelled` or an
      id after the last `await`. In an `@Observable` model the task handle is
      `@ObservationIgnored`: the pattern type-checks under the app settings, and fails
      without it, because `deinit` cannot reach the handle. The task unwraps its
      `[weak self]` after each `await`: a probe showed a loop that unwrapped once at the
      top keeping its owner alive for good.
    - Tests own their resources, since Swift Testing runs them in parallel. A timer is
      exposed with `.updatesFrequently` instead of announced on every tick. A changed UI
      flow gets `performAccessibilityAudit()` in its UI test, and the hand-back asks the
      user for a VoiceOver walk, which a session cannot do.
    - A fix made during review reruns the checks it touches. That sentence sits in the
      Swift verification section, not in the loop, whose text all bodies share.
    - `!`, `try!` and `as!` are banned in tests too. A probe showed a failed force unwrap
      killing the whole Swift Testing run, with no summary and other tests' results lost,
      where `try #require` recorded one failure and the run went on. The rubric item that
      protected `best!` in a test was dropped. Every review had flagged it, rightly.
  - **Revised again after a second review** (2026-10-23), on four points:
    - **Task lifetime.** "Capture `[weak self]` and unwrap after each `await`" was too
      blunt. A probe released two main-actor models while their tasks ran. With
      `Task { [weak self] in await self?.run() }`, the model lived until `run()` returned,
      30 ticks later. With `self` held strongly only inside each step, it was freed after
      a few ticks, and the task ended. The rule now has work tied to a view run in
      `.task { await model.run() }`, which SwiftUI cancels. A stored long-running task
      holds `self` strongly only inside each short step. A finite task whose work must
      finish, such as a save, captures `self` strongly on purpose, because a weak capture
      would drop it. All three patterns type-check under the app settings.
    - **Audit coverage.** Apple's WWDC23 session 10035 says "An audit is limited to the
      elements on the screen". So a UI test navigates to each changed screen and state
      and audits each, and the manual VoiceOver and large-text walk stays.
    - **XcodeGen.** The exact version is recorded beside `minimumXcodeGenVersion`.
      **Rejected for now:** pinning it through Mint or a tools package. Neither Swift
      repo has CI, both are built on one machine, and the generated project is not
      committed, so a version drift cannot change a tracked file. The rule pins it once
      a project has CI or a second machine.
    - **`.updatesFrequently`** is only for a value that changes too often to announce,
      like a running timer. Apple's text says the trait makes VoiceOver poll for
      changes.

    The Swift body is now 9.5k, about 130 characters under the cap with its header, and
    less when the header names a long marker path. The review eval was not run again:
    these changes touch none of the fixture's seeded defects.
  - **The harness.**
    - It counts a read of a body in `conventions/` as its own mechanism. It leaves out a read
      that printed nothing or got Claude Code's "file unchanged" notice. A partial read,
      such as `grep` or `sed -n` on a body, still counts as a copy.
    - Only a body marks a rule present before the first file tool, and a call that reads a
      body is not that file tool.
    - It counts stubs in context the way it counts copies.
    - The deferred Phase 0 items are fixed: `cat < f` is a read, `../` is normalised, the
      fallback parser reads redirects, and `export` and `for` loops are followed. Each of
      the four surviving mutants got a fixture.
    - A case's rubric is stored in each run record for the grader.
    - The 18 mutants of the harness and the 19 of the two hooks all fail the suites, the six
      the review planted included.
    - Ruff 0.17 needs `--target-version py39`. Its default proposes `datetime.UTC`, which
      macOS's Python 3.9 lacks.
  - **Rejected:**
    - A `**/*.swift` glob that skips `ios/`. Native apps use any layout, and the React
      Native stub costs under 300 characters.
    - Detecting Swift from any `project.yml`. Other tools use the name, like the fixture's
      deployment file.
    - XcodeGen's `platform: [iOS, tvOS]` read as one multi-platform target. XcodeGen makes
      one target per platform from it. `supportedDestinations` is the multi-platform form,
      and both count.

- **A rule reaches each context once: SessionStart injects its body, and a native load brings
  only a pointer stub** (2026-10-22, Phase 0 of the language-rules plan; Phase 1 builds it).
  Claude Code now loads a path-scoped rule natively on more than a Read, and no load checks
  whether the same text is already in context. `scripts/eval_config.py` measured this two
  ways. The first was the live config on the fixture repos in `evals/phase0-loading/`: CLI
  2.1.307, one run per case, with haiku at low effort, since loading is the harness's
  behaviour and not the model's. The second was the recorded transcripts.
  - **Only SessionStart puts a rule in context before planning.** A planning prompt with no
    file access had the injected rule and no native load.
  - **Every native load after an injection is a second copy.** In the fixture runs these
    loaded it: a Read, an Edit with no Read before it, a Write of a new file, and `cat`,
    `head`, `sed -n`, `tail` or `grep -n` on one file. A `cat` of two files and a piped `cat`
    loaded nothing.
  - **Before 2.1.307 the native loads were intermittent.** This was the first native load of
    a session, attributed to the whole turn that triggered it, over the recorded sessions:
    - A single-file Bash read loaded nothing on 2.1.289 or 2.1.292, and loaded consistently
      from 2.1.295.
    - A Write loaded the rule 5 times in 16.
    - An Edit loaded it 0 times in 19.

    The 2026-09-24 audit had seen only Read loads. Unreliable native loading is one more
    reason the injection stays.
  - **Resume keeps both copies.** The hook log records a `resume` injection, but it reaches
    neither the transcript nor the request.
  - **Compaction drops both copies.** SessionStart then injects the rule again, and the next
    read loads it natively again.
  - **Real sessions confirm it.** The sample is the 260 recorded sessions: Claude Code's
    30-day retention window plus 2 older ones. Eval sessions and sessions in `~/.claude` are
    left out.
    - 129 of the 224 sessions that got `java.md` held it twice.
    - 69 of the 208 that got `frontend.md` held it twice.
  - **A second copy costs about 3.0k tokens for `java.md` and 3.4k for `frontend.md`.**
    - In the fixture runs, a native load grew the next API call by 3,214 to 3,262 tokens for
      `java.md` and by 3,626 for `frontend.md`.
    - A read with no native load grew it by 180, which is the file content alone.
    - In characters, the second copy is 8,615 for `java.md` and 9,272 for `frontend.md`.
  - **Subagents get rules only natively.** 219 of 233 subagent rule loads were in
    `code-reviewer`. The rest were in Explore and Plan.
  - **The fallback leaks.** `frontend.md` loaded natively on an Angular `.ts`, `.scss` and
    `tailwind.config.js`, and on a React Native `App.tsx`. Detection refuses both repos.

  The owner chose the design on 2026-10-22, and Phase 1 builds it:
  - Rule bodies move out of `rules/` into `conventions/`, and `session-rules.sh` injects
    them from there.
  - Each `rules/<lang>.md` becomes a stub of about 300 characters that keeps the `paths:`
    fallback. The stub tells a context with no `[session-rules <lang> …]` block to read the
    body.
  - Each stub starts with `[rule-stub <lang>]`. The harness tells a stub from a body by that
    marker. Without it, a stub would count as a second copy of the body, and Phase 1's
    deduplication would look as if it had failed.
  - Reviewer lenses read the body explicitly.
  - Phase 1 also narrows each stub's globs.

  **The harness.**
  - A case file refuses a prompt that names a skill it tests, since that would test access
    and not selection.
  - Cost and tokens come from the session's cumulative totals. Per-step `usage` leaves out
    subagents and compaction, and `total_cost_usd` already accumulates across `--resume`.
  - Its first review found both of these after the numbers were first reported. The figures
    above are the corrected ones.
  - Its third review corrected the token cost, the CLI version and the version thresholds in
    this entry.

  **Rejected:**
  - Keeping both mechanisms. More than half of the Java sessions carry about 3k duplicate
    tokens, and each new language would add the same.
  - Injection with no fallback. A repo the detector misses would get nothing: one nested
    deeper than two levels, or a session started in a parent folder. Explore and Plan would
    lose the rules too.
  - Native loading only. A rule would arrive at the first file access, after planning.
  - A body in `rules/` without `paths:`. A rule with no `paths:` loads in every session.

- **A bean takes at most seven constructor dependencies, and the reviewer judges each touched
  class whole** (2026-10-21). PersonalFinance's application services had grown to 14 fields
  (SeedImporter), 13 (InvitationService) and 11 (InstrumentService). Each diff was simple, so
  each passed review. The Sonar gate did not report them because S107, the parameter-count
  rule, is not in PersonalFinance's `sonar-rules.txt`. Their constructors carry no
  annotation, so S107 would have flagged all three. Four changes came out of it:
  - **The limit is a test.** `hexagonal-module-bootstrap` → `tests-architecture.md` §
    Constructor dependencies records each bean over the limit with its exact count, and fails
    until the record matches the code. The template was compiled and run against ArchUnit
    1.4.1 on eight fixture sets. An exact match passed. A new bean, a bean that grew, a bean
    that shrank, a bean that dropped under the limit, a 9-parameter class built by a `@Bean`
    method, and an import with no bean at all each failed, with a message naming the entry.
    A plain class with 10 parameters was not counted, and neither was an 8-component record
    that a `@Bean` method only passes as an argument.
  - **`rules/java.md` § Simplicity** states the limit and how to split, and adds four habits:
    a type over a comment, two methods over a selector flag, the rule of three for
    abstractions only, and deletion reported in the hand-back.
  - **`code-reviewer` reads every touched class whole.** A class the diff pushes over the
    limit, or grows while already over, is 🟡. One already over that does not grow is a 🔵
    note, so a small fix does not become a refactor. A recorded count that goes up, or a new
    entry for a class that was under the limit, is 🔴. The entries recorded when the test is
    introduced, and renames, are not.
  - **`CLAUDE.md` asks for plain sentences** in the comments that stay.

  The first review caught two errors in this change. The S107 rationale had cited its
  `@Autowired` and `@Inject` exemption (sonar-java's `TooManyParametersCheck`), which does not
  apply to PersonalFinance's constructors. The first template passed when it found no bean,
  because a stream over `JavaClasses` loses ArchUnit's `failOnEmptyShould`.

  **Rejected:**
  - S107 in the rules file. It skips constructors marked `@Autowired` or `@Inject`, and it
    keeps no record of the classes already over. Turned on, it blocks each of them the next
    time the gate sees it, instead of letting them shrink step by step. The test also runs in
    every `mvn test`, not only in Claude sessions.
  - `FreezingArchRule`. It matches a violation by its text. With the count in the message,
    any change to the count fails as a new violation, and only `freeze.refreeze=true` moves
    the record, for every frozen rule at once. Without the count, a recorded class grows
    unseen.
  - The number in prose only. Nothing would enforce it.
  - Rewriting memory files in plain sentences. The idea that agents copy the style of
    `MEMORY.md` into code comments is unmeasured, and the index is one line per entry by
    design. The explicit rule in `CLAUDE.md` is the direct lever.

  **Pending:** a consolidation skill, run at milestones on the recorded classes, waits for the
  owner's prompt text. PersonalFinance gets the test from a session in that repo.

- **The Sonar gate's bypasses after 0.8b0's fifth review are closed** (2026-10-12, PersonalFinance
  step 0.8b0b). Each route was measured before it was guarded: read from the analyzers' own code
  in `~/.sonar/cache` (sonar-java 8.41, SonarJS 13.8), then planted beside a control on the
  26.8 server, every planted form hiding the issue its control showed.
  - **Never accepted, reason or not:** `@Generated` (`javax|jakarta.annotation[.processing]`,
    resolved by type on a class or method by sonar-java's `GeneratedCodeFilter`, an any-rule
    filter) and, in Java, a `\u` escape for a printable ASCII character: `@\u0047enerated` hid its
    method's issues, since Java decodes escapes before it reads a token. javac's parser finds
    `@Generated` (below); a text match for the word, tried first, refused comments, imports and
    `Generated.class` with no way out, and went with the second review. Excluded code is generated
    code: changed Java under the base's root-pom exclusions must carry a generator's header in its
    first 20 lines.
  - **`@SuppressWarnings` takes string literals on one line.** sonar-java resolves values with
    `asConstant`, so `"a" + "ll"` and a constant holding "all" suppress everything, and
    `@SuppressWarnings( // reason` with `"all")` on the next line passed the old per-line audit.
    "all" is compared case-sensitively and javac keys lower-cased (from the bytecode).
  - **javac settles what a Java annotation is.** The first review pass found the text audit
    still blind to spellings javac reads: a comment or a line break inside the annotation
    (`@/**/SuppressWarnings/**/("all")`, `@java.lang` / `.SuppressWarnings` / `("all")`), and
    identifier-ignorable characters, which javac drops from a name, raw (U+200B, U+00AD, controls)
    or escaped (`@Suppress\u0000Warnings`), each resolved by sonar-java's ECJ as the real type. Every
    pass had found one more spelling: matching syntax with regexes is a list of spellings, and a
    language accepts more. `scripts/SuppressionAnnotations.java` has javac's parser list every
    `@SuppressWarnings` and `@Generated` of the changed Java files, and the hook refuses any
    `@Generated`, any "all", and any `@SuppressWarnings` whose source is not one line of printable
    ASCII with string literals, the form the line audit reads. About 0.35 s per Stop that changed
    Java. The line audit stays for the reasons, NOSONAR and the other languages. A NUL, which ends
    a line for macOS awk, is dropped before either reads a file.
  - **SonarJS's vocabulary, completed.** NOSONAR is upper-cased with JavaScript's `toUpperCase`,
    which maps U+017F to S, the only code point that becomes a letter of NOSONAR (checked over all
    of them): `// noſonar` suppresses. ESLint trims a comment (any JavaScript space) and reads a
    directive from its first word (`eslint`, its `-env|-enable|-disable[-next]-line` forms,
    `exported`, `global(s)`), so `/*` alone then `eslint rule: off`, `/* eslint` alone, and a
    no-break space before `eslint` are inline configs. Source lines are split where Java or
    JavaScript ends them (a lone CR; LS and PS) and those spaces read as spaces.
  - **Code kept out of analysis is reported.** Changed Java under the root pom's exclusions passes
    on a generator's header, which anyone can write: each such file and its header line join the
    once-per-set systemMessage that reports justified suppressions.
  - **Every changed source file must be analysed** (`--indexed`). Exclusions are one way out of
    analysis; a directory that is no module, a source root, a size limit or a language setting are
    others, and a file Sonar never read has no findings. Measured: a Java file under an orphan
    `src/main/java` passed the old gate. Java under `src/main|test/java`, poms, and the JS project's
    code by SonarJS's and its CSS analyzer's default suffixes go to the gate, which refuses one with
    no component in its project's latest analysis. A `.d.ts` is left out: SonarJS excludes
    `**/*.d.ts` by default, and it holds declarations only.
  - **The JVM's option variables are unset for the scans.** `JAVA_TOOL_OPTIONS`, `JDK_JAVA_OPTIONS`
    and `_JAVA_OPTIONS` reach the scanners' JVMs: `-Dsonar.java.file.suffixes=.none` there turned a
    file with two findings clean on the old gate.
  - **SonarJS's generated-code detection is off** in the gate's scan
    (`sonar.javascript.detectGeneratedCode=false`). It skips 140 of SonarJS's 575 rules on files a
    codegen manifest in the repository marks (`.openapi-generator/FILES`, among others), so a
    manifest could silence hand-written code. Found in the bundle while measuring, beyond the review's
    list; the property was accepted by the server, but no manifest was planted.
  - **Instance settings are an allowlist**, as project keys' already were: only the five keys this
    server held, each changing no analysis (identity, base URL, authentication, the quality mode,
    whether a child profile may drop an inherited rule, which the profile check refuses anyway).
  - **Settings are checked without a rules file**, and `--provision` makes them match without one.
  - **A pom's Sonar properties are compared with xmllint's by name and value**, not by count: a
    CDATA section in a value kept the count and changed what Maven reads.

- **The Sonar gate applies a committed rule set, scans TypeScript and counts duplication**
  (2026-10-11). Simon's IDE reported 326 issues on PersonalFinance while the gate, run on the
  whole project, reported 0. The gate counted correctly, but it measured something else:
  - **Rules.** SonarQube for IDE, standalone, had 42 Java rules switched on beyond Sonar way
    (S1541 cyclomatic complexity, S138, S1151, S109 and others); the local server ran plain
    Sonar way. A repo's `.sonar-gate` now names a rules file (`rules = FILE`).
    `sonar-gate.sh --provision` builds "<repo> way" per language as a child of Sonar way, so
    Sonar way's own updates still flow in, and assigns it to the project keys. The IDE moves to
    connected mode on the same server: one rule set, in the repo.
  - **Drift is refused, every run.** Each listed rule must be active with the listed values and
    the rule's defaults elsewhere, no unlisted rule activated or overridden, every Sonar way rule
    still active (a child may deactivate an inherited rule), every other language on the
    built-in Sonar way, no project key carrying a setting of its own beyond what `.sonar-gate`
    gives it (an allowlist, so a key a SonarQube release adds is caught too), and nothing that
    narrows analysis set at instance level, where `sonar.global.exclusions` beats any scanner's
    value and a component read reports it as inherited. Issues marked accepted or false positive
    on the server still count, and so does every status but FIXED (`IN_SANDBOX` included). A
    rule listed with parameters other than Sonar way's is refused as an `override`, with its
    values, and the hook asks a reason for any rule line added with parameters. Security
    hotspots are read from their own API too; on 26.8 a planted S2245 came back as an issue, and
    the hotspots API held nothing apart. The review loop found each of these holes in an earlier
    version.
  - **The IDE's scope comes from the server.** In connected mode it reads only server-side
    exclusions, never a pom's or Git's ignores, so it counted the generated jOOQ, OpenAPI and
    TypeScript code the gate skips: 627 issues against the gate's 317, then 316 once
    `ide-exclusions` reached it. That setting is provisioned as `sonar.exclusions` alone on the
    first project key, the one the IDE binds to. The root pom's own `sonar.exclusions` overrides
    it in the gate's Maven scan, and the gate refuses to run when the pom sets none (read with
    `xmllint`). `sonar.test.exclusions` is not provisioned: the pom sets none, so it would have
    reached the gate's Java tests. The IDE re-reads server settings only when it re-syncs: unbind
    and bind the project to force it.
  - **A narrowed rules file or `.sonar-gate` blocks.** A rule or value taken out of the rules
    file, or in `.sonar-gate` the JS project or rules file changed or dropped, scope moved off
    `project`, or an IDE exclusion added, needs a `#` line added in the same change naming it and
    why. The base's comments justify nothing, and a rule or setting commented out is not its own
    reason: dropping `rules` alone would switch every server-side check off.
  - **The suppression vocabulary is measured, not assumed.** Copying Java's `NOSONAR` to
    TypeScript let `// nosonar` through. Planted lines scanned on this server showed SonarJS
    honouring a comment starting with NOSONAR in any case (not one in mid-comment), every ESLint
    disable directive, and an inline `/* eslint rule: off */` config, which hides an issue with no
    warning at all; the CSS analyzer honours NOSONAR and stylelint's directives; sonar-java
    resolves `@SuppressWarnings` by type, so `@ SuppressWarnings` and the qualified form count.
    The audit reads every form in every file, and each needs its reason (an ESLint or stylelint
    one, its ` -- description`).
  - **Hand-rolled readers are checked against real ones.** The pom audit's count of Sonar
    properties must equal `xmllint`'s, or the change is refused: a CDATA section holding `<!--`
    hid a property Maven read. A `.properties` line ends at LF, CRLF or a lone CR, and a
    continuation drops its leading spaces, as `properties-file` reads them.
  - **A changed pom goes to the gate**: the Maven scan analyses each module's pom.xml.
  - **Every Sonar property in a pom or a `sonar-project.properties` needs its reason**, not a list
    of the narrowing ones; one in `.mvn/maven.config` or `.mvn/jvm.config` is refused outright.
    `sonar.lang.patterns.<lang>` drops a language from analysis and `sonar.java.source` disables
    version-gated rules; the review loop's third pass found both passing the list. Only new or
    changed properties are audited, so this costs one comment per Sonar property added.
  - **TypeScript was never scanned.** The Maven scanner reads Maven modules only, and the hook
    triggered on `*.java` alone. `js-project = DIR` adds a second project key, scanned with a
    pinned `@sonar/scan`, and the hook's file set takes in that directory's sources.
  - **Duplication is a measure, not an issue**, so a gate counting issues never saw it. Each
    duplicated block in main code is now a finding, with its partner's location.
  - **`scope = project`** blocks on any finding anywhere. It answers the open question about
    commits on the base branch for the repos that set it.
  - **Failures** used to exit 1 with stderr, which shows the user only its first line and Claude
    none of it (hooks reference, checked this day). They now reach the user whole as a
    systemMessage, as does a gate still red after three rounds.
  - **Tokens left argv.** curl reads `user =` from a config on stdin, and both scanners take
    `SONAR_TOKEN` from the environment. `test_hooks.py` pins that no token reaches a command
    line.
  - **Reads use the administrator's user token** when the Keychain holds one
    (`sonar-local-admin-token`). The analysis token still runs the scans, but the measures and
    duplications APIs refuse it for want of Browse permission. *Rejected:* a dedicated
    non-admin reader account. It would mean one more account and token to set up, on a
    localhost-only server where `--provision` needs the admin token anyway. What that token
    could do to the gate's verdict (accept issues, set exclusions, loosen the profile) is what
    the drift checks above refuse. Revisit if the server ever serves more than this machine.
  - **Findings come from the analysis they were scanned for.** After reading them, the gate checks
    each project's latest analysis is still the one it scanned or cached, and fails otherwise.
  - **Freshness.** A project whose inputs match its last analysis from here is read, not
    rebuilt: the commit, the diff and untracked files under its paths, the rules file and
    `.sonar-gate`, the script, the server's version and the profiles' stamps. The record in
    `$TMPDIR` holds the analysis key its own task produced (`api/ce/task`'s `analysisId`), so
    another run's analysis never passes for it. A Java-only change no longer re-scans the
    TypeScript, and the reverse. Both projects cold take 2 min 18 s here.
  - **The scanners run without the environment that carries properties**: every `SONAR*` and
    `npm_config_sonar*` variable, `MAVEN_OPTS` and `MAVEN_ARGS` are unset (the npm scanner reads
    `SONAR_SCANNER_*` and a JSON variable as properties, per its source). The npm scanner runs
    from the gate's scratch directory with `sonar.projectBaseDir`, so no project `.npmrc` reaches
    it. User-level `~/.m2/settings.xml` and `~/.npmrc` are the owner's and stay in effect.
  - **A watchdog stops the gate at 360 s**, whole process group, Maven included, before Claude
    Code's 400 s hook timeout would discard the hook's output; the user is told. A signal aimed at
    the hook is forwarded to that group. Every API call is bounded at 60 s.
  - **The JS project counts whole.** The hook lists any changed file under `js-project`, since
    its analyzer reads `.mts`, `.cts`, `.html` and more; the NOSONAR audit reads every changed
    file but prose, and the root pom's exclusions exempt none of the JS project's. In its
    `sonar-project.properties` a size cap (`maxFileSize`, `filesize.limit`) is audited like an
    exclusion, and an escaped key is refused outright, since the scanner decodes it.

  Measured on PersonalFinance right after: 323 findings, 317 issues and 6 duplicated blocks,
  where the gate had said 0. The backlog is plan step 0.8b there.

- **The maintainer notes left `AGENTS.md`, which loaded far beyond `~/.claude`**
  (2026-10-11). The 09-24 entry kept this file as `AGENTS.md` on the finding that it loaded
  in sessions started in `~/.claude`. Since v2.1.277, Claude Code reads `AGENTS.md` directly
  when no `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` sits in the working
  directory or above it (`~/.claude/CLAUDE.md` does not count), and it then reads every
  `AGENTS.md` and `.claude/AGENTS.md` up the tree (memory docs, § When Claude Code reads
  AGENTS.md). `~/.claude/AGENTS.md` is the home directory's `.claude/AGENTS.md`, so it
  loaded as project instructions in every session under `~` whose project has no
  `CLAUDE.md`, subagents included, Explore and Plan aside (159 of 173 PersonalFinance
  subagent transcripts carry it, 140 of them code-reviewer's). The transcripts agree:
  - **First seen** on 2026-09-22, CLI 2.1.280, in a work repo.
  - **Loaded:** all 123 PersonalFinance sessions that record their instruction files (7
    record none), and sessions in MineSweeper, Tetris, a Java demo and two work
    repos, none of which has a `CLAUDE.md`.
  - **Not loaded:** Wealthpay, Pictures and uigen, which have one, and sessions started in
    `$TMPDIR`.

  The decision log had grown the file to 37 KB, 13.2k tokens by `/context` on 2026-10-09,
  about a sixth of a PersonalFinance session's first-turn input (75.5k–78.5k). Three
  things kept it unseen:
  - **The 09-24 check** was a `/context` run in `~/.claude`. From the first load on 09-22
    to 09-27, every `/context` run outside `~/.claude` was in Pictures or Wealthpay, which
    have a `CLAUDE.md` and so never load it.
  - **From 09-28 it was listed, not hidden:** `/context` in Tetris (09-28) and
    PersonalFinance (09-29, 10-04, 10-09) showed it as a Project file at 8.4k–13.2k tokens,
    and nobody read the row against this file's first paragraph.
  - **`hooks/log-instructions.sh`** gets no InstructionsLoaded event for an `AGENTS.md`
    read directly (memory docs, § Where AGENTS.md differs from CLAUDE.md).

  The notes are now `MAINTAINERS.md`, which nothing loads. `AGENTS.md` keeps a pointer,
  scoped to changes `git status` would show, so that a memory write does not send a session
  here and a new agent, rule or skill file does. A session editing this config from a
  project without a `CLAUDE.md` is still sent here; one from a project with a `CLAUDE.md`
  is not, and only README's row points here then.
  **Rejected:**
  - Deleting `AGENTS.md`: nothing would send a config session to the decision log.
  - The pointer in `CLAUDE.md`: it would read as one of Simon's working rules, in a file
    that holds only those.
  - `instructionFiles: "claude-md"` under `cc-plugin-agents-md@builtin`, or a
    `claudeMdExcludes` pattern: either would also stop the `AGENTS.md` of repos that rely on
    one, or this file's pointer in `~/.claude` sessions.

- **The sandbox is off; the 2026-09-26 trial is over** (2026-10-09). Even without the ask
  rule, a command that needs Docker, Testcontainers, a browser or Xcode has to carry
  `dangerouslyDisableSandbox`. Auto mode's built-in Safety Bypass Flag rule refuses a flag
  named that way unless the user names it, and it refused two Playwright e2e runs that
  evening. Every interruption since the trial began traced back to the sandbox, so Simon
  turned it off through `!`: auto mode refuses edits to its own settings. Secrets keep the
  protections they had before the trial: the Read denials on `.env` and credential files,
  `bash-guard.py`, and the classifier. **What is lost:**
  - Credential files are no longer hidden from Bash at the OS level.
  - The two Sonar tokens are back in every command's environment.
  - A secret read that names no file (`grep -r KEY .`), the gap `bash-guard.py` left to the
    trial, is open again.

  **Rejected:** an `autoMode.allow` exception naming the flag (after `"$defaults"`, which
  keeps the built-in exceptions). It would have kept the sandbox, but put one more rule
  between Simon and every build. The `sandbox` block stays in settings, so turning it back
  on is one key.

- **Package registries are pre-allowed for sandboxed commands** (2026-10-09). With the ask
  rule below gone, the next prompt was a host review. A sandboxed command that reaches a
  host outside the allowlist has to name it in `allowed_domains`, and the review sent some
  of those calls to Simon. Over the same fortnight, `registry.npmjs.org` was named 40 times,
  and 7 of those calls waited more than 10 s. That count includes slow commands, so it is an
  upper bound on prompts. `sandbox.network.allowedDomains` now lists npm, PyPI and its file
  host, Maven Central under both names, and `raw.githubusercontent.com`. The Maven hosts,
  the PyPI file host and the raw host only serve files. PyPI uploads go to
  `upload.pypi.org`, which stays off the list. An npm publish needs a token, and the sandbox
  hides `~/.npmrc`. Simon applied the change through `!`, because auto mode refused the edit.
  **Left under review:**
  - The market-data APIs (eodhd, Yahoo, Twelve Data), whose calls carry keys.
  - `api.github.com`, which accepts writes from any token in the environment.

  *Superseded the same day:* the sandbox is off; see the entry above.

- **The sandbox stays on, and unsandboxed retries go to the auto-mode classifier** (2026-10-09).
  The 2026-09-26 trial's ask rule, `Bash(dangerouslyDisableSandbox:true)`, made every
  unsandboxed retry wait for Simon. Over 26 Sept to 9 Oct, that came to 1,525 prompts, about
  117 a day and over 200 a day in the last week. On quick commands, a retry waited a median
  26 s and a p90 of 5 min, against 1 s sandboxed. Simon refused 5. The prompts gated routine
  work, which kept the agent from working unattended:
  - **Builds and tests made up most of them.** `./mvnw` accounts for 470, mostly
    Testcontainers needing the Docker socket, and `docker` for 436. npm and Playwright add
    126, Xcode and Swift 99.
  - **`excludedCommands` almost never applied.** An entry covers a call only when every
    command in it matches. A `cd`, a file redirect, `; echo` or a pipe to `tail` keeps the
    whole call sandboxed, and the CLAUDE.md line that sends builds to a log in `$TMPDIR`
    gives nearly every build one of those. The entries stay for the bare forms, such as the
    Sonar gate run by hand.

  Simon deleted the rule through `/permissions`: auto mode refused the edit as
  self-modification. Secrets keep their protections. Credential files and `.env` stay hidden
  from Read and from sandboxed commands, the two Sonar tokens stay stripped from their
  environment, and `bash-guard.py` still applies to every command. **Rejected:**
  - Turning the sandbox off. The friction came from the prompt, not the sandbox.
  - `allowUnsandboxedCommands: false`. Docker and Testcontainers cannot run sandboxed, so
    integration tests could never run.
  - The Docker socket in `network.allowUnixSockets`. A sandboxed `docker run -v ~:/h` could
    then read every secret, with no classifier review.

  *Superseded the same day:* the sandbox is off; see the first entry.

- **`bash-guard.py` judges environment dumps by segment, like its other checks** (2026-10-01).
  The dump check was the last one matching the raw command, so a `|`, `;` or `(` inside quotes
  counted as a separator. In 30 days of transcripts, about half its denials were false: quoted
  regex alternations such as `'(set|get)'`, a jq filter holding `"Bash(env)"`, and Swift's
  `private(set)` in a heredoc, which blocked writing Swift through Bash. The other five were
  `env | grep` checks on variables whose names were known, so the denial now names
  `printenv NAME`. Two parsing changes came with it:
  - **A `(` glued to a word no longer ends a segment**, in every check. `name(` never opens a
    subshell.
  - **A `$(…)` inside a quoted token is read as commands**, which keeps `echo "$(env)"` denied.

  The check now also catches `env 2>/dev/null | grep`, which the regex missed. One case went
  the other way. The regex caught `bash -c "x; env; y"`, because separators fell on both sides
  of `env` inside the quotes, and it already missed `bash -c 'env | grep'`. Both are one known
  gap, pinned in `scripts/test_hooks.py`.

- **Bash output is bounded by a CLAUDE.md line, not by a cap or a hook** (2026-10-01).
  `/doctor` put Bash results at 171k tokens, 17% of a session's context. The fortnight's 72
  transcripts held 2,854 Bash results, 6.3M characters in all:
  - **File reads made up 68%.** These were `cat`, `sed -n`, `head` and `for … cat` loops,
    which auto mode's system prompt invites. Up to 1.3M characters went to files the same
    session also opened with Read or changed with Edit or Write. Edit refuses a file that
    only `cat` has shown, and two Edits in the fortnight failed that way, so a `cat` before an
    edit reads the file twice. The count matches basenames, so it is an upper bound.
  - **Builds and tests made up 16%.** The 242 of 393 runs that went through `tail`, `grep` or
    a log averaged 1.1k characters. The rest printed everything, about 5k each.
  - **No result passed 30k characters.** The default `BASH_MAX_OUTPUT_LENGTH` already caps a
    single result.

  The line asks for Read on any file that may be edited, ranges for the rest, and builds
  through a log in `$TMPDIR`. **Rejected:**
  - A lower `BASH_MAX_OUTPUT_LENGTH`. It cuts the middle, so a file or a stack trace loses
    lines without a sign, and under 6% of results passed 10k characters.
  - Teaching `bash-guard.py` to deny `cat` on a long file. Each denial costs a round trip,
    and that guard exists for safety, not context.

  Whether the line changes behaviour is not yet measured.

- **Code the base's Sonar exclusions keep out of analysis is out of the suppression audit**
  (2026-09-30). PersonalFinance's step 1.2 generated 21 jOOQ classes, and the Stop hook refused
  each one. jOOQ puts `@SuppressWarnings({ "all", "unchecked", "rawtypes", "this-escape" })` on
  every class it writes, the audit read every added java line, and Sonar never analyzes those
  files: the root pom excludes them with a reason. The gate went red on code the analyzer cannot
  see, and it would do the same for every new jOOQ table and every openapi-generator module.
  Simon chose to exempt that code in the hook.
  - **The exemption follows the base's root pom.** Its `sonar.exclusions` are read as Sonar reads
    them, as ant patterns: `**/` spans any leading directories, none included, and `*` and `?`
    stop at a `/`.
    - **Only exclusions the base already has count.** One added in the same change is held to
      the pom audit and exempts nothing until it is committed, so every exemption rests on an
      exclusion whose reason has been seen. The first candidate read the working tree's pom. An
      existing fixture caught it: an uncommented exclusion then hid its file's `NOSONAR` from the
      report.
    - **Only the root pom counts.** A module pom's exclusion exempts nothing, and neither does a
      pattern not rooted in `**/`, which is matched from the repository root. Both can only make
      the audit stricter than Sonar, never laxer.
    - **The element scanner is shared.** `pom_audit` and the exemption use one set of awk
      functions, so the two cannot read a pom differently.
  - **Rejected:**
    - A jOOQ generator subclass that prints no class annotations. It would cover jOOQ only, and
      it would change what javac says about generated code for the gate's sake.
    - Leaving the lines until they are committed. The repo has no remote, so the base is `HEAD`,
      and every Stop before the commit blocks.
  - `scripts/test_hooks.py` pins seven rows. The three rows that exempt failed against the
    previous hook. The four that must stay audited pass on both.

- **Pom-level Sonar suppressions are held to the NOSONAR rule, and reports reach the user
  through `systemMessage`** (2026-09-30). PersonalFinance's step 0.8 suppressed a rule
  with `sonar.issue.ignore.multicriteria` in its root pom, and the Stop hook neither
  blocked nor reported it: its audit read only added `*.java` lines. A session red on
  `Foo.java` could exclude that file in the pom, and the gate would answer "clean" with
  nothing printed. Two changes in `hooks/sonar-gate-on-stop.sh` close that:
  - **The audit.** A Sonar property that excludes, skips or narrows analysis is held to
    the NOSONAR rule. That covers `*exclusions`, `*inclusions`, `*suffixes`,
    `sonar.issue.ignore.*`, `sonar.issue.enforce.*`, `sonar.skip`, `sonar.sources` and
    `sonar.tests`.
    - **The reason.** In a `pom.xml`, each new or changed property needs an XML comment
      on its own lines, or one ending just above its block of adjacent suppression
      properties. That is how a three-line `multicriteria` entry is naturally commented.
      The report shows each reason, so a property that borrows its block's comment is
      visible as such.
    - **Poms are read as elements, with comments blanked.** A value spread over several
      lines is then one property, judged at its opening line. The start tag may carry
      whitespace or attributes, and the end tag whitespace. Maven 3.9.16 reads all of
      these forms as the same property, and a first scanner that knew only
      `<sonar.x>value</sonar.x>` let each one through. A self-closing or unterminated tag
      ends at its own `>`, so it swallows nothing after it.
    - **Only a pom is accepted.** Any such property in `.mvn/maven.config` or
      `.mvn/jvm.config` blocks. The reason is one audited place: `maven.config` does
      take `#` comments since Maven 3.9, while `jvm.config` takes none.
    - **The audit runs even when no java file changed**, though nothing is scanned
      then. `--files` would be empty, which is why "scan on a pom change" was rejected.
    - **Blocking every pom suppression was rejected too:** it would forbid excluding
      generated code.
    - **Known limit:** a value routed through a `${property}` is not traced.
  - **No diff parsing.** Both audits compare each file with its blob at the fork point.
    The first version parsed `git diff -U0`. Review broke it two ways: a `-diff`
    attribute hid the lines, and `diff.interHunkContext` renumbered an uncommented
    exclusion onto an unrelated comment. Its here-strings also failed under macOS bash
    3.2, which creates here-document temp files outside `$TMPDIR`, and an audit that
    cannot run now exits 1 rather than pass.
    - **Lines are counted, not collected as a set,** so a second copy of a grandfathered
      bare NOSONAR is new.
    - **Paths come through `core.quotePath=false`.** A quoted non-ASCII path used to fail
      the file test and was skipped.
    - **A file moved since the fork point is audited as new,** so its old suppressions
      need reasons too. That was judged cheaper than mapping renames.
    - **One `grep -l` pass picks the Java files worth auditing.** Per-file processes had
      cost about 7.5 ms per changed file on every Stop, fingerprint hits included.
  - **The channel.** The hooks reference says stderr from a hook that exits 0 "goes to the
    debug log only, never the transcript, and Claude never sees it". The justified-NOSONAR
    report had gone there since it was written, and its fixture pinned stderr, so it had
    never reached anyone. Reports now go out as a `systemMessage`, the channel
    `session-rules.sh` already uses. Now that the channel is visible, each set is shown
    once: it is keyed per repo in `$TMPDIR`, without line numbers, so an edit above a
    suppression does not report it again.

  Deleting `.sonar-gate` while the fork point still has it is the other quiet way off the
  gate. It now draws a `systemMessage` on every Stop while the marker stays deleted. A repo
  that never had the marker stays silent. `scripts/test_hooks.py` pins all of it, and
  every row that pins a fix failed against the version before it. Every pattern is ASCII,
  so the text tools run under `LC_ALL=C`: in a UTF-8 locale, macOS awk aborts on a Latin-1
  byte and grep stops matching the line. The Latin-1 rows pin the locale for that reason.

- **The self-review loop is one text in two rules, and the reviewer reads the frontend
  checklist rather than copying it** (2026-09-27). The loop had drifted: `java.md` gained
  the re-review-after-edit rule and "the loop adds no quality of its own", and
  `frontend.md` never did. Both rules now end with the same `### Self-review loop`
  section, and `hooks/validate-rules.sh` blocks a Stop that leaves the two different or
  either missing. The check sits at Stop because the session that edits one copy has no
  reason to run the test suite; `scripts/test_hooks.py` pins it. The reviewer's frontend
  lens had carried a copy of the WCAG 2.2 AA checklist; it now reads `frontend.md` and
  keeps only the severity. One shared loop file was rejected: the `paths:` fallback load
  would deliver the rules without it, and `session-rules.sh` would have to append a second
  file to each injection. The section is about 760 characters, and `frontend.md` has
  about 360 left under the injection cap.
- **Agent prompts give reasons, not emphasis** (2026-09-27). "MUST", "non-negotiable" and
  "hard requirement" came out of both agent files wherever the reason already stood beside
  them: recent models follow a system prompt closely, and emphasis makes them over-apply a
  rule. Both agents run as subagents and cannot ask the user mid-run, so each "ask" or
  "confirm" became something a subagent can do: return the question to the caller, name
  the assumption in the review, or state the tradeoff in the final message. The PDF build
  changed in substance, not only in tone: it waited for an agreement that could never
  arrive mid-run, and now runs when the request asks for the PDF. The reviewer keeps its
  Staff-engineer role, since Anthropic's prompting guidance recommends one.
- **Claude Code hooks are carved out of `shell.md`'s shebang, strict mode, `--help` and
  `--dry-run`** (2026-09-27). The eight bash hooks pin `#!/bin/bash` without
  `set -euo pipefail`. That broke both halves of the rule's second hard rule, and none of
  them has `--help` or `--dry-run`. Rewriting them was rejected. A hook's exit code is
  its interface: 0 passes, 2 blocks, and anything else does not block on its own, so a
  crashing guard fails open. Under `set -e`, a failing command's own status would become the
  hook's, and a stray 2 would block by accident. For the same reason, the rule's "2 means
  a usage error" never applies to a hook. The two MCP wrappers in `~/bin` already keep
  strict mode, which stops a failed Keychain read from starting a server with an empty
  key. They are exempt from the shebang clause only. shellcheck and shfmt still apply.
  Three hooks and `md2pdf.sh` failed shfmt, and all four now pass it.
- **`format-on-stop.sh` keeps formatting the whole changed set** (2026-09-27). It formats
  everything `git status` lists, so uncommitted edits the turn never touched get
  formatted too. A per-turn snapshot, which would record blob hashes at UserPromptSubmit
  and format only what changed, was not built. It would add a hook and per-session state
  to one that never blocks and runs only in repos with a prettier config, and the
  behaviour is now documented in README instead.
- **SubagentStop validates only the agents that can edit** (2026-09-27). The 09-24
  denylist skipped `code-reviewer`, `Explore` and `Plan` and checked every other agent
  type by default. That included `claude-code-guide`, which only answers questions and
  could be blocked by drift it cannot fix. Under the sandbox, no subagent can fix
  `skills/`, `rules/` or `hooks/` through Bash either. The matcher is now an allowlist:
  `general-purpose`, `claude`, `learning-doc-writer` and `statusline-setup`. An editing
  agent missing from the list still does not escape the check, because the main
  session's Stop hook runs the same validators at the end of the turn. `fork` is left out
  on purpose. The check covers the whole tree, so any listed agent can be blocked for
  drift the main session has not finished, but a fork is the likeliest case, since it is
  spawned mid-change with the main session's context. When a new agent that can edit
  is added, add it to the matcher too.
- **Secret environment variables are named in managed settings, not here** (2026-09-26).
  The sandbox strips a variable only when `sandbox.credentials.envVars` names it, and a
  token's name can name its project, which in this public repo can be a client's. The two
  project-token entries moved to machine-level managed settings. Deny entries merge across
  every settings scope, so the effect is unchanged: both tokens are absent from a sandboxed
  environment and present outside it, checked both ways. The unpushed commits that carried
  the names were rebuilt before any push. The shell rc still exports both tokens, so
  unsandboxed processes and hooks inherit them. The stronger option, having each consumer
  read the Keychain as brave-search does, was not taken. A new secret variable goes to
  managed settings the same way.
- **This file loads in `~/.claude` sessions, and stays** (2026-09-24). `/context` showed
  it injected as project memory at session start, which contradicted this file's first
  paragraph and README's row, both of which said nothing here loads. Renaming it out of
  the loader's reach was rejected: the cost falls only on sessions that edit this config,
  and those are the sessions that need the decision log. The two sentences were fixed
  instead. *Superseded 2026-10-11:* it also loaded in every session under `~` whose
  project has no `CLAUDE.md`, so the notes moved to `MAINTAINERS.md`; see that entry.
- **The Sonar gate skips a re-run when no fingerprinted input changed** (2026-09-24).
  In an opted-in repo, every Stop re-ran the Maven build and analysis while the branch
  differed from its base in any java file, so a turn that touched only docs paid for a
  full scan. A green run now leaves a fingerprint — the base commit, then the diff and
  untracked files for java sources, poms and the contract schemas `rules/java.md` treats
  as code, then `.sonar-gate`, the gate and the hook — and a Stop that matches it skips
  the scan. The test suite derives the schema list from `rules/java.md`, so a drift
  between the two fails the suite. Resources and `.mvn/` stay out on purpose, because counting them
  would make every config-only turn a Maven build again. Resolved dependencies and the
  server's profile are not in the working tree at all; dependency declarations are, in
  the poms, and those count. Only green runs record the fingerprint, and it is taken
  before the change set is read, so nothing landing later can be recorded as clean.
  The cache would have made one gate flaw permanent, so the gate was fixed first. With
  no task id in the scanner's report, or a server task still unfinished after 300s, it
  read the issues API anyway, which answers from the previous analysis. A stale green
  used to last one Stop; cached, it would have lasted until the next fingerprinted
  change. Both cases now exit 1, which the hook reports as "checks are OFF" and never
  records. The base was a hardcoded `main`, so a `master` repo compared against HEAD and
  never gated committed branch work; it now comes from `origin/HEAD`, then `main`, then
  `master`. No repo carried `.sonar-gate` on that date, so the change waits for the
  first one that opts in.
- **MCP keys leave the session environment, and the servers are pinned** (2026-09-24).
  The shell rc exported the Brave key, and an old launcher script exported it again, so
  every Claude session and each of its Bash subprocesses carried it; `bash-guard.py` can
  only deny the obvious ways to print it. Now a wrapper reads the key from the Keychain
  and runs the server, the pattern fal-ai already used. That takes the key out of the
  sessions' environment, not out of reach: the item answers any process that runs
  `/usr/bin/security`, and any process running as this user can. The wrapper starts the
  server from `/`, because Claude Code starts MCP servers in the session's project
  directory, where the server's dotenv would load that project's `.env`.
  All three `npx` servers ran unpinned — playwright as `@latest`, from an absolute nvm
  path that the next Node upgrade would break. brave-search, the one holding a key, now
  runs from a local install with a lockfile, like fal-ai, so its whole tree is pinned.
  context7 and playwright are pinned on plain `npx`, the top-level package only, and
  launch with `--prefix /`: npx fetches metadata at every start from the registry the
  launch directory's `.npmrc` names, so a project pointing at an unreachable registry
  stopped them starting — a 70s failure, against 1s with the flag. `cd /` would have done
  the same, but it needs a wrapper per server, and `--prefix /` needs none: npm looks for
  the project `.npmrc` at the prefix, without moving the process. (playwright takes its
  workspace and output directory from the client's first MCP root and falls back to its
  working directory only when a client sends none, so `cd /` would not have moved them
  either.) The project-scope
  `.mcp.json` held only a duplicate playwright, so it went, along with its enablement
  keys. Hook commands in `settings.json` now use `~/.claude/…`,
  because the absolute paths named the account and would break for any other user. That
  relies on shell form: an exec-form hook (`args`) runs without a shell, so `~` would
  stay literal, and a hook that cannot start is a non-blocking error — a guard would
  fail open.
- **The retired agents' memories were triaged, not abandoned** (2026-09-24). Since the
  09-09 retirement, 41 memory files had loaded nowhere. Each lesson went where it has to
  load:
  - Java conventions and verification discipline into `rules/java.md`, about 30 lines.
  - Placement rules into `hexagonal-ddd-java` and `java-observability`.
  - Two lines into `rules/shell.md` and one into `rules/frontend.md`.
  - Three cross-project preferences into CLAUDE.md.
  - Project-bound lessons into the (untracked) project memories.
  - One review lens into the reviewer's own memory.

  Covered and stale ones were deleted: restore on evidence, from an archive outside this
  repo. Simon settled two conflicts:
  - **AAA markers:** see the comment-doctrine entry.
  - **The service floor:** controllers never touch repositories, and reference-data CRUD
    is `controller → service → repository` with no ports. The skills had said "flat
    controller → repository", and a retired memory contradicted them.

  The migration had also dropped a qualifier: prose is out of scope for the delegated
  skill dimensions, not for review. Load-bearing docs go through `code-reviewer` again.
- **claude.ai plugin sync is off in Claude Code; the connector policy is private**
  (2026-09-24). Nine plugins enabled on the claude.ai account synced into every session:
  91 skills and about 80 MCP servers. The skill listing is capped at 1% of the context
  window, so it overflowed and cut descriptions starting with the least-used skills,
  including the Anthropic document skills. In a Java repo, Skills cost 9.9k of the 33.2k
  tokens at session start. `syncClaudeAiPlugins: false` keeps them on claude.ai and in
  Cowork; synced *skills* (`syncClaudeAiSkills`) stay on. The claude.ai connectors stay
  available, but ask rules on their outbound, hard-to-undo tools and one denied connector
  live in machine-level managed settings, never in this public repo. There are 28 ask
  rules as of 2026-09-26, up from 9, re-derived from the connectors' tool lists that day.
- **Rules load by repo type at SessionStart** (2026-09-24). The open question — does a
  path-scoped rule fire when a file is read through Bash? — was answered from the
  transcripts, and the answer was no:
  - Only the Read tool triggers a load. Two sessions made eight Edit/Write calls each on
    `.java` files and never got the rule.
  - Auto mode reads through `cat` and `sed`. After the architect's retirement,
    `rules/java.md` reached 3 of 7 Java-editing main sessions. The self-review loop it
    prescribes ran in 2 of those 3 and in 0 of the other 4 (5 of 9 before the retirement).
  - Of the loads that did happen, 37 of 40 landed in subagents, whose context never
    reaches the main session.

  `hooks/session-rules.sh` now injects `java.md` or `frontend.md` when the repo is Java
  or React/Next, which is deterministic and costs nothing elsewhere. The `paths:`
  frontmatter stays as a fallback. *Amended 2026-10-22:* on 2.1.307, an Edit, a Write or a
  single-file Bash read also loads a path-scoped rule. Before that, those loads were
  intermittent. Each one adds a second copy beside the injection. See that entry.

  Rejected alternatives:
  - The rules back in CLAUDE.md: every session pays for them.
  - A skill: model-invoked, the same non-determinism.

  `shell.md` lost its `paths:` and loads everywhere (~770 tokens), because scripts appear
  in any repo. A "read this first" pointer would have been as unreliable as a skill.
  `hooks/log-instructions.sh` logs every load, so step 9 of the fix plan measures the
  change instead of assuming it.
- **The reviewer's read-only contract is a hook, not a promise** (2026-09-24).
  `memory: user` auto-enables Write and Edit, so "read-only on the repo" was held by the
  prompt alone. `hooks/reviewer-guard.py` runs from the reviewer's own frontmatter, and
  only while it does:
  - Edit/Write land only in its memory directory or scratch.
  - `git` is allowlisted rather than blocklisted, so an alias or a rare write verb is
    denied by default.
  - In-place edits, editors, `eval`, `sh -c`, write-capable `gh`, file-mutating commands,
    and redirects or `tee` outside scratch are denied.

  It fails closed. Test runners and builds still pass, because the prompt's
  `git status` invariant covers their side effects. `SubagentStop` now skips
  `code-reviewer`, `Explore` and `Plan`: a read-only agent cannot fix README drift, so
  blocking it up to eight times achieved nothing. *Superseded 2026-09-27:* the matcher is
  now an allowlist of editing agents, forks excepted; see that entry.
- **`bash-guard.py` judges each command segment, pinned by a fixture table**
  (2026-09-24). An audit ran 66 commands through the old guard and 25 got the wrong
  answer. A template name anywhere in a command (`.env.example`) exempted all of it, so
  `diff .env.example .env` read the real file unasked; `+ref` and `:ref` pushes and
  `rm -r .` passed; and joined lines produced false denials (`rm -rf build`, then
  `cd ..` on the next line). Now lines and `; && || |` split segments, templates are
  exempt per match, deny beats ask, and `scripts/test_hooks.py` pins both directions.
  The shebang is `/usr/bin/python3`: `env python3` resolved to a pyenv shim that fails
  in any repo pinning an uninstalled interpreter, so the guard was silently off there.
  Out of reach by design: a secret read that names no file (`grep -r KEY .`) — the
  sandbox trial owns that.
- **The architect layer is retired** (2026-09-09). `java-backend-architect` became
  `rules/java.md`, a path-scoped rule that loads only when a Java file is read;
  `script-engineer` became `rules/shell.md`; `discovery-analyst` became the manually
  invoked `scoping` skill; the two frontend agents were deleted outright. Evidence over
  the preceding month: 67 `code-reviewer` spawns, 3 `learning-doc-writer`, 1
  `java-backend-architect`, 0 for the other four — while seven agent descriptions cost
  ~3,170 words in every session's startup context, and Java skills were being loaded
  from main sessions rather than from the architect. `hooks/validate-agent-contracts.sh`
  went with them: it existed to police architect↔reviewer coupling that no longer has
  two sides. Recover any of them from tag `pre-best-practices-2026-09-07`.
  *Measured 2026-09-24:* the retirement was due for review after two weeks. A transcript
  audit over 2026-09-09 to 09-24 stood in for the weekly snapshots first planned. The
  retirement stands. What came back was loading, not agents: the SessionStart rule
  injection and the memory triage, both above.
- **Three architect stances restored into `rules/java.md`** (2026-09-09, same day).
  The first cut of the rule kept the stack conventions and the verification protocol but
  dropped what the architect prompt had owned outright rather than delegated to a skill:
  the contract-first mandate, modular-monolith-by-default, and the non-functional priority
  ordering with its review-scope rule. No skill carries them, so they were simply gone.
  Restored on Simon's call. The rule's `paths:` grew to cover `.avsc`, `.avdl`, `.proto`
  and OpenAPI YAML at the same time — a rule stating that a schema change *is* a code
  change cannot fire from a `**/*.java` scope, because the file being edited is the
  schema. 36 → 93 lines, against the architect's 424.
- **`rules/frontend.md` added; `code-reviewer` gains a frontend lens** (2026-09-09).
  The first pass retired both frontend agents with no replacement, on 0 spawns in the
  audit window — but 0 spawns meant "has not come up lately", not "will not". Restored on
  Simon's call: `frontend-architect`'s owned standards became a path-scoped rule, and
  `frontend-code-reviewer`'s six review dimensions became a **frontend lens** in
  `code-reviewer.md`, mirroring the standalone-script lens already there. Without that
  second half the rule would tell a session what to build while the only surviving
  reviewer judged a `.tsx` diff by backend axes. 658 agent lines → 161 rule lines plus a
  43-line lens.
- **The calibration tier taxonomy is shared vocabulary**, not an enforced contract:
  *throwaway / internal tool / production service / critical financial system*. It
  originates in `code-reviewer` ("Calibrate your bar") and is emitted by the `scoping`
  skill, so a project's business tier flows into review calibration during the build.
  Reword it in one place and the other stops speaking the same language.
- **Fetch-only spawns take Sonnet; judgment spawns never do** (2026-08-13). A sub-agent
  that opens an already-identified source and reports what it says is retrieval. Anything
  that judges — a reviewer above all — is the opposite job: out of its depth, a reviewer
  does not return "unsure", it returns a confident ✅, and it is the last gate before work
  ships.
- **Comments default to none in generated code** (2026-08-11). The rule lives in
  `CLAUDE.md` § Code comments at user scope, and `code-reviewer` carries the matching
  **Comment noise** bullet in its code-level layer — which is what makes the review
  enforce it rather than merely assert it. Keep both halves: doctrine alone and breaches
  ship unopposed; reviewer bullet alone and nobody was told the rule they are judged on.
  The fix was structural — `skills/hexagonal-module-bootstrap` had carried 119
  explanatory comment lines inside its Java fences, so copying a template meant copying
  its comment density. *Amended 2026-09-24:* test phase markers (`// Arrange`,
  `// Act`, `// Assert`, `// Act + Assert`) are the one always-on exception. They were
  Simon's convention all along, but they were recorded only in the retired architect's
  memory, so the 08-11 cleanup stripped them from the templates too. Both halves carry
  the exception now, and the templates' 23 test methods are marked again. Simon also
  settled one carve-out: a repo whose tests already label phases with comments in another
  vocabulary (`// given` / `// when` / `// then`) keeps its vocabulary. Spacing and
  BDD-named APIs do not count.
- **Reviewers hold conditional memory-write access** (2026-07-08, superseding the
  memory-file half of a 2026-04-23 read-only rule). The April rule conflated "don't
  modify the reviewed artifact" — still absolute — with "don't keep your own notebook",
  which froze the reviewer's learning loop. The risk it actually guarded against stays
  blocked by the loop-context ban above.

## Known open questions

- **Known limits of the Sonar gate after PersonalFinance step 0.8b0b** (2026-10-12), left by the
  owner's decision to stop that step after two review passes. *Accepted as they are, the same day:
  the owner closed the gate's hardening for good, since it lists nearly every finding and more
  passes cost more than they find. Do not reopen them without the owner asking.*
  - A `@SuppressWarnings` line passes as justified when a string literal on it holds `//`
    (`@SuppressWarnings("java:S1075") static final String URL = "https://example.com";`): the
    reason check finds the URL's `//`. It is reported to the user, not silent, and it predates the
    step. The fix: a `//` only after the well-formed annotation, or the helper reading the comment.
  - `scripts/SuppressionAnnotations.java` needs JDK 16 or later from PATH, run in the repository,
    so a `.java-version` there picks the JDK. When it fails, the whole gate is OFF for the turn, and
    the message gives no cause: its stderr is not shown.
  - Regenerated jOOQ code lists every changed file in the systemMessage, truncated at 9500
    characters; grouping by excluded root and header would read better.
  - Changed Java outside `src/main|test/java` is neither required to be analysed nor flagged; a
    `pom.xml` that is no module (a test fixture) would be refused as not analysed; `.jav` files,
    which sonar-java reads, are outside the hook's file set.
  - Configuration outside the repository still reaches the scans: `bin/mvn` sources
    `~/.mavenrc` and `/etc/mavenrc` after the gate's `env -u` (`MAVEN_SKIP_RC` would stop it), and
    `npx` re-exports `~/.npmrc` keys. User-level configuration was recorded as the owner's in 0.8b0;
    `api/ce/task`'s scanner context could check every channel at once, unconfirmed on 26.8.
  - Whether sonar-java reads a NOSONAR spelled with `\u` escapes in a comment was not measured;
    the hook refuses every printable-ASCII escape in Java either way.

- **Index flags hide a file from the Sonar gate** (2026-09-30).
  `git update-index --assume-unchanged` or `--skip-worktree` on a pom or a java file
  takes it out of `git diff --name-only`. The file then drops out of the trigger, the
  suppression audit and the scan alike. This predates the pom audit. A cheap guard would
  refuse, or warn, when `git ls-files -v` shows a lowercase tag or `S` on a gated path.
- **A commit on the base branch leaves the Sonar gate's view** (2026-09-30). In a repo with
  no remote, where work lands directly on `main`, the fork point is `HEAD`. A mid-turn
  commit therefore takes a red file out of the diff, and the gate never looks at it again.
  Nothing guards this. Sessions commit only when asked, and PersonalFinance's steps run
  the gate before committing. *Answered 2026-10-11 for repos that set `scope = project` in
  `.sonar-gate`:* the base commit is in the fingerprint and the whole project is counted, so a
  commit cannot take a finding out of view. Under `scope = changed` it still can.
- **Test-running discipline**: the reviewer can run tests, but the invoking session is
  responsible for green tests before invocation. Whether the reviewer re-runs them is
  non-deterministic. Acceptable; revisit if review latency becomes a concern.
- *Answered 2026-09-24 — see the decision log:* path-scoped rules do not fire on a
  Bash read, nor on Edit/Write; only the Read tool triggers them.
- *Answered 2026-09-27, CLI 2.1.283:* a resumed session carries one copy of each
  injected rule, not two. `session-rules.sh` runs again with `source: "resume"`, but the
  resume writes no second injection record to the transcript. The resumed turn's prompt
  was 35 tokens larger than the first turn's: the first reply plus the second prompt. A
  second copy of the Java rule would have added about 2k. Which copy survives, the
  original or the fresh one, was not measured. Either way the hook needs no resume guard,
  since a guard that dropped the fresh copy could leave none.
