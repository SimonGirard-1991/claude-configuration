---
name: python-migration
description: >-
  Move an existing Python project (pip, pip-tools, Poetry or setuptools alone) onto the
  uv stack that ~/.claude/conventions/python.md sets: the commit series, the commands for
  each starting point, and the build, install, CI and container checks that prove nothing
  broke. Use once the user has agreed to the move. Not for a new project, a script that
  already carries PEP 723 metadata, or code tied to another interpreter.
---

# Moving a Python project onto the uv stack

`~/.claude/conventions/python.md` sets the end state and the policy: the move is a change
of its own, made once the user agrees. This is the procedure. Run each command on the
project and read its output. uv changes between minor versions, so a step that surprises
you is checked against uv's current documentation.

## The commit series

1. The code renamed under `src/<package>/`, alone, so `git log --follow` and blame keep
   its history. A backend that names the package's location changes in the same commit:
   setuptools `package-dir` or `packages` in `[tool.setuptools]` (`package_dir` in
   `setup.py` or `setup.cfg`), Poetry's
   `packages = [{ include = "<package>", from = "src" }]`, or uv_build's
   `[tool.uv.build-backend] module-root` where it is set.
2. Tooling and lock, as below for the project's starting point.
3. `uv run --locked ruff format`, alone.
4. The fixes, one concern per commit: ruff's safe fixes, then each behaviour change
   (DTZ, BLE, TRY, B) in a commit of its own.

The series lands when the body's checks and the checks under "What must still work" pass.

## The Python version

`<version>` is the Python the project runs on now, 3.11 at least. An older one upgrades
first, in a change of its own. The body's rules use 3.11 APIs (`enum.StrEnum`,
`datetime.UTC`, `typing.assert_never`).

## Tooling and lock, by starting point

- **One script with a `requirements.txt`.** It becomes a PEP 723 script, not a package.
  Lock before adding, or the lock resolves past the file's pins:
  `uv init --script s.py --python <version>`, `uv lock --script s.py`, then
  `uv add --script s.py <direct dependencies> -c requirements.txt`.
- **No `pyproject.toml`.** `uv init --bare --package --name <package> --python <version>`
  writes only that file, and `uv python pin <version>` adds `.python-version`. Without
  `--bare`, uv adds a template module and a `[project.scripts]` entry for a `main` the
  code may lack.
- **pip-tools.** `uv add -r requirements.in -c requirements.txt` keeps the pinned
  versions.
- **A frozen `requirements.txt`.** `uv add <direct dependencies> -c requirements.txt`.
  `uv add -r` on a fully pinned file makes every transitive package a direct dependency.
- **Poetry.** `uvx migrate-to-uv --keep-current-build-backend` converts the project at its
  locked versions. Diff what it writes. uv reads neither `poetry.lock` nor Poetry's
  groups, and a Poetry 1.x file without a `[project]` table syncs as an empty project. The
  tool is for Poetry only: on a pip-tools project that already had a `[project]` table, it
  kept `dependencies = []` and deleted the requirements files.
- **setuptools with only `setup.py` or `setup.cfg`.** Their metadata moves into a
  `[project]` table first: name, version, dependencies, `console_scripts` as
  `[project.scripts]`, package data. setuptools stays as the backend. `uv init --bare`
  here would write version 0.1.0, no dependencies and no entry points.
- **Any backend that reads a `[project]` table** (setuptools, hatchling, flit, pdm-backend,
  uv_build). The backend stays, and `uv lock` reads the table.
- Then, in every case, `uv add --dev ruff mypy "pytest>=9"` and the body's configuration
  block. The block replaces any `ruff.toml`, `.ruff.toml`, `mypy.ini`, `.mypy.ini`,
  `pytest.ini` or `.pytest.ini` in the tree: each overrides `pyproject.toml`, so its
  settings fold into the block and the file goes in the same commit.

## What must still work

- **The built package.** Build it, install the wheel in a fresh environment, and run each
  entry point and each code path that reads a packaged file, as a user would:

  ```bash
  out="$(mktemp -d)"
  uv build -o "$out"
  uv venv "$out/venv" && uv pip install --python "$out/venv" "$out"/*.whl
  cd "$out" && "$out/venv/bin/<entry point>" <arguments>
  ```

  Running from outside the repository catches a path that only resolves from its root.

  setuptools ships a data file only when `MANIFEST.in` or
  `[tool.setuptools.package-data]` names it. A `src/` package that read a JSON resource
  built and installed without complaint, then failed with `FileNotFoundError`. uv_build
  ships every file in the module directory except caches.
- **Every consumer of the old files.** Before the requirements or Poetry files go, search
  the repository for `pip install`, `requirements` and `poetry`, and move each consumer:
  - CI installs with `astral-sh/setup-uv` and `uv sync --locked`, as uv's GitHub Actions
    guide shows.
  - A Dockerfile copies uv from `ghcr.io/astral-sh/uv:<uv version>` and runs
    `uv sync --locked` with `UV_NO_DEV=1`, as uv's Docker guide shows.
  - A consumer that still needs a requirements file gets one generated with
    `uv export --locked --format requirements.txt --no-dev --no-emit-project --no-header
    -o requirements.txt`. Without `--no-emit-project` the file holds `-e .`, which pip
    refuses beside hashes. CI reruns the export and diffs it against the file, since
    `uv sync --locked` does not notice a stale copy. It is never edited by hand, and it
    goes when that consumer moves.

## After the move

The body's Verification and its self-review loop apply as for any change. The reviewer
rates the move against the body's configuration.
