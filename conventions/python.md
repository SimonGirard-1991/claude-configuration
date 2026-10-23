# Python conventions

Python projects managed with uv, existing ones included. Facts about these tools and the
standard library come from current documentation (Context7 first), never from memory:
their defaults change between minor versions. A standalone script carries PEP 723
metadata instead of a project, and everything else here applies to it. Structure scales
with the change: a small script gets no layer it does not need, and keeps every rule for
what it does, money above all. Code tied to another interpreter, such as `~/.claude`'s
hooks on `/usr/bin/python3` 3.9, keeps that interpreter's floor and existing checks.

## Stack

- `uv init --package --python <version>` makes a new project, where `<version>` is the
  newest stable CPython that every dependency ships wheels for. The project gets a `src/`
  layout, the `uv_build` backend, `requires-python` and `.python-version`, and commits
  `uv.lock`.
- Dependencies come from `uv add`, never `pip install` or a hand-written
  `requirements.txt`. ruff, mypy and pytest sit in the `dev` group
  (`uv add --dev ruff mypy "pytest>=9"`), and `uv.lock` pins their versions.
- Their configuration lives in `pyproject.toml`:

  ```toml
  [tool.ruff.lint]
  extend-select = ["ANN", "B", "BLE", "DTZ", "I", "PT", "PTH", "S", "TRY", "UP"]
  ignore = ["S603", "TRY003"]

  [tool.ruff.lint.per-file-ignores]
  "tests/**" = ["S101"]

  [tool.mypy]
  strict = true
  warn_unreachable = true
  files = ["src", "tests"]

  [tool.pytest]
  strict = true
  testpaths = ["tests"]
  ```

  `extend-select` adds to ruff's default set, which `select` would replace. S603 flags
  every subprocess call, the list form required below included. TRY003 wants messages
  built inside the exception class, and here each raise site states its own. With
  pydantic, `[tool.mypy]` also takes `plugins = ["pydantic.mypy"]`. `uv init` creates no
  `tests/`, and mypy and pytest fail until it holds a first test.
- mypy is the type checker, not pyright or ty.
- An existing project moves onto this stack in a change of its own, never inside a fix or
  a feature, as the `python-migration` skill lays out. A session proposes it once per
  project, and a refusal or deferral, kept in the project's memory, holds until the
  project changes materially. Until then, a change follows the code rules the project's
  Python supports, writes tests for its runner, adds dependencies with its tooling, and
  passes its own checks.

## Types

- Every function is annotated, tests included (`-> None`).
- `Any` stays where an untyped source produces it and is narrowed at once, by a pydantic
  model or `isinstance`. No function takes or returns `Any` to quiet the checker.
- A `cast` or a `# type: ignore[code]` carries a comment saying why the type holds.

## Data

- Domain values are `@dataclass(frozen=True, slots=True)` where they hold invariants or
  evolve apart from the input format. A closed set is an `Enum` (`StrEnum` for text), or a
  `Literal` when it needs no identity or behaviour. A `match` over either ends with
  `case _: assert_never(value)`, so mypy names a member the match missed.
- pydantic only at a boundary that receives untrusted data: a file, an HTTP body, the
  environment. Its models are frozen with `extra="forbid"`. Where domain dataclasses
  exist, each model becomes one at that boundary, and domain code never imports pydantic.
  A plain transformation tool may work on the validated models.

## Money and numbers

- An accounting amount is a `Decimal` built from a `str` or an `int`, never from a
  `float`: `Decimal(0.0075)` is 0.00749999…. RUF032 catches a float literal, not a float
  variable. In JSON an amount is a string: a pydantic `Decimal` field reads a JSON number
  through a float, losing digits past the 17th and trailing zeros, so a number goes
  through `json.loads(text, parse_float=Decimal)`, then `model_validate`.
- Rounding is decided per business operation: one named function applies
  `quantize(unit, rounding=…)` where that operation posts its amount, and the currency and
  the operation set `unit`, a power of ten (0.01 for CHF, 1 for JPY, 0.001 for BHD):
  `quantize` keeps only its exponent, so a 0.05 cash step needs its own function. Nothing
  rounds to a business unit before that, and computation runs in one stated `decimal`
  context, 28 significant digits by default. Two rounding modes in one code base each need
  a written reason.
- Statistics such as returns, volatility or scores may be `float`. An amount never is.

## Time

- Datetimes are timezone-aware: `datetime.now(UTC)`, and `.astimezone(ZoneInfo(name))`
  for local time. Never `utcnow()` or `utcfromtimestamp()`, which return naive values.
- A `date` is a calendar day, such as a booking or trade date. A `datetime` is an instant.
  One becomes the other only through a named time zone.
- "Now" is a parameter, or an injected clock, so tests pin it. Only the entry point reads
  the real clock.

## Errors, processes and I/O

- No bare `except` and no swallowed exception. Catch the narrowest type, then handle it
  completely or re-raise with context (`raise StatementError(…) from error`).
  `contextlib.suppress` takes a named exception only: `suppress(Exception)` passes ruff.
- Exception classes follow what callers do differently, not raise sites (PEP 8). A
  package or script has one base, `class <Name>Error(Exception)`. An expected failure,
  such as invalid input the program must reject or a missing tool, raises that base or,
  where a caller handles it apart, a subclass such as `MissingToolError`. Its message
  names the input and the cause. A caller that breaks a function's contract has a bug,
  and gets `ValueError` or `TypeError`, as the standard library does.
- The entry point catches the base with `sys.exit(f"error: {error}")`, which prints one
  line on stderr and exits 1. It alone catches `Exception`, logs it with
  `logger.exception`, traceback included, and exits 1.
- Other diagnostics go through `logging`: `logger = logging.getLogger(__name__)` per
  module, and `logging.basicConfig` once in `main()`, whose handler writes to stderr.
  stdout carries data only.
- A subprocess runs as `subprocess.run([exe, *args], check=True, timeout=…)`, never with
  `shell=True`. Text output it reads takes `capture_output=True, encoding="utf-8"`, binary
  output no `encoding`, and large output a file as `stdout`. Where the exit status is
  data, as for `git diff --quiet`, the call passes `check=False` and reads `returncode`.
  `shutil.which` resolves `exe` once.
- Paths are `pathlib.Path`. Text I/O passes `encoding="utf-8"`. Every network call has a
  timeout. Secrets come from the environment or the Keychain, never from source or argv.

## Testing

- pytest with plain test functions: `@pytest.mark.parametrize` for cases that differ only
  in data, `tmp_path` for files, `monkeypatch` only at a process boundary.
- Unit tests use no network and no real clock. Time, randomness and I/O clients are
  injected, and tests pass fakes.
- Each test marks its phases as `~/.claude/CLAUDE.md` defines the markers.

## Verification after non-trivial changes

1. Off the stack, the project's own checks. On it, `uv run --locked ruff check`,
   `uv run --locked ruff format --check`, `uv run --locked mypy` and
   `uv run --locked pytest`, each through a log in `$TMPDIR`.
   `--locked` fails on a stale `uv.lock`, which a plain `uv run` rewrites without saying
   so. Never `uvx mypy` in a project: its environment lacks the project's dependencies.
2. A PEP 723 script commits the lockfile that `uv lock --script s.py` writes. It has no
   project, so its checks name it and pin ruff and mypy at their newest PyPI releases
   (`<ruff>`, `<mypy>`), which the lockfile does not cover. mypy needs the packages of the
   script's own environment, which `uv sync --locked --script` builds from that lockfile,
   and `<floor>`, the version its `requires-python` starts at: mypy otherwise checks
   against the Python uvx runs it on. A script whose logic needs tests against its
   dependencies becomes a project, since PEP 723 has no test dependencies.

   ```bash
   uvx ruff@<ruff> check --extend-select ANN,B,BLE,DTZ,I,PT,PTH,S,TRY,UP \
     --ignore S603,TRY003 s.py
   uvx ruff@<ruff> format --check s.py
   uv sync --locked --script s.py
   uvx mypy@<mypy> --strict --warn-unreachable --python-version <floor> \
     --python-executable "$(uv python find --script s.py)" s.py
   ```
3. Run the self-review loop below, telling `code-reviewer` this is a **Python diff** so it
   applies its Python lens. A fix made during the review reruns each check above that
   covers what it changed before it goes back to the reviewer.

### Self-review loop

Spawn `code-reviewer` with: what changed and why, the calibration tier
(throwaway / internal tool / production service / critical financial system), the scope
(paths or git range), and the line `Invocation: self-review loop, iteration N of 3`.
Address 🔴 and 🟡; judge 🔵 on merit; cap at 3 iterations, then escalate to the user with
what is outstanding. A verdict covers only the diff it saw: every edit after a review goes
back through the reviewer within the cap, a 🔴 fix without exception; past the cap, hand
the fix to the user marked unreviewed. The loop adds no quality of its own: submit correct
code first, and mid-loop fix only the accepted findings, adding nothing new.

Relay any **Proposed memory** note verbatim; record it only on user approval.
