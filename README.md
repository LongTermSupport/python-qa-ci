# py-qa-ci

One QA entry point for Python projects, built for the Defence Before Fix method
(https://defence-before-fix.github.io/): bespoke rules hosted in Pylint, blocking enforcement
through a single command, offline documentation for every identifier it prints, a project record
for every exception, and an enumerable list of active defences.

Status: early (0.x). Conformance is **partial**; see [docs/CONFORMANCE.md](docs/CONFORMANCE.md).
Licence: MIT ([LICENSE](LICENSE)). Changes, and how to upgrade: [CHANGELOG.md](CHANGELOG.md)
(0.2.0 renamed the tool from python-qa-ci).

Defence Before Fix is a phase that runs before a defect is fixed: the instance is treated as
evidence of a class, and the defence that detects the class is built and seen to fire before the
fix is made. A failing run prints a one-line pointer to the specification and to its
[agent prompt](https://defence-before-fix.github.io/defence-before-fix-project-prompt.md).

## Install

Pin an exact tag, as a development dependency of the project, so the tools run in the project's
own environment and see its dependencies:

```bash
uv add --dev "py-qa-ci @ git+https://github.com/LongTermSupport/py-qa-ci@v0.4.0"
uv run py-qa run
```

Python 3.11 or later. The detectors are pinned exactly by this package (Ruff 0.16.10, mypy 2.4.0,
Pylint 4.1.2 with astroid 4.3.4), so a new release of one of them reaches a project only as a
deliberate upgrade of py-qa-ci. The runners, pytest and coverage.py, are floors, since the
project's test suite already depends on them.

## What it runs

`py-qa run` executes three phases in a fixed order. Every format and detector lane runs, so
one invocation reports every static finding; if any of them fails, the runners do not run.

| Phase     | Lane (`-t` name) | What                                                                                                                              |
| --------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| format    | `fmt`            | `ruff format`, or Black with `formatter = "black"` (fixes locally; `--no-fix`, `--ci` or a non-empty `CI` variable check instead) |
| detectors | `record`         | the project record: structure, justifications, budget, expiry (`pyqaci.record.*`)                                                 |
|           | `suppression`    | every suppression comment and configuration setting held to the record (`pyqaci.suppression.*`, `pyqaci.record.stale`)            |
|           | `summary`        | the agent summary region is current (`pyqaci.summary.stale`), when a summary file is set                                          |
|           | `docs`           | every bundled and project defence has a complete page (`pyqaci.docs.dangling`)                                                    |
|           | `ruff`           | `ruff check`, the project's Ruff configuration or the bundled one                                                                 |
|           | `mypy`           | mypy, the project's configuration or the bundled strict one                                                                       |
|           | `pylint`         | Pylint as the bespoke rule host: the bundled plugin, the project's plugins, nothing else                                          |
|           | a check's `name` | each `[[tool.py-qa.check]]` the project declares among the detectors, in the order declared                                       |
| runners   | `test`           | pytest, under coverage.py with `coverage.fail_under` when the `coverage` switch is on; or the project's own `test.command`        |
|           | a check's `name` | each `[[tool.py-qa.check]]` declared with `phase = "runners"`, in the order declared                                              |
|           | `audit`          | pip-audit over the environment (off by default; needs network and the `audit` extra)                                              |

Options: `-t <lane>` (repeatable; overrides the switches), `--skip <lane>` (repeatable; every
lane but these), `-p <path>` (repeatable; one file is enough; limits the format and detector
lanes to those paths and does not run the runners), `--diff` and `--base <ref>` (a diff run,
below), `--json <file>` (also write the outcome of every lane, and a diff run's test selection,
as JSON), `--no-lock`, `--no-fix`, `--ci`, `--fail-fast`. Every identifier a tool prints reaches
the output unaltered. The run ends with a table of every lane, its result and the seconds it
took, and the total. Exit codes: 0 pass, 1 a lane failed, 2 a usage or configuration error, 3
another `py-qa run` holds the lock.

One run at a time: `py-qa run` holds an advisory lock, `py-qa/run.lock` in the work tree's git
directory unless `lock` names another file, and a second run started meanwhile exits 3 naming
the holder's pid. The kernel releases the lock when its holder exits, however it exits. `lock = false` or `--no-lock` turns it off.

Other commands, none of which runs a defence:

- `py-qa rules [--json]`: every active defence, derived from the configuration in force, then
  the project record and any scan exclusions
- `py-qa rule-doc <identifier>`: documentation for any identifier a finding prints, offline
- `py-qa rule <identifier> <path>...`: the harness, which runs one rule alone on the paths
  given (Pylint messages, Ruff codes, and the suppression rules); exit 0 it did not fire, 1 it
  fired, 2 it could not run
- `py-qa docs-check`: fail if a listed defence has no complete page
- `py-qa record check|list`: validate, or list, the project record
- `py-qa summary [--check]`: write, or check, the agent summary region
- `py-qa tools`: every lane, whether it is on, and the tool behind it with its installed version
- `py-qa affected [--base <ref>] [--json]`: the tests a diff run would run, each with the changed
  files that reach it, and every changed file nothing accounts for; exit 1 when the diff map
  names a test that does not exist

## Project checks

A check the project already has, a script that exits non-zero on a finding, becomes a lane:

```toml
[[tool.py-qa.check]]
name = "spelling"                                    # the lane, and the identifier it fails with
command = ["{python}", "scripts/check_spelling.py"]  # run without a shell; {python} is py-qa's
description = "Write British English in prose."      # the standing instruction py-qa rules lists
doc = "scripts/check_spelling.py"                    # what py-qa rule-doc spelling prints
phase = "detectors"                                  # or "runners", after the test lane
paths = ["**/*.md"]                                  # a diff run runs it only when one changed
diff_command = ["{python}", "scripts/check_spelling.py", "{files}"]  # and like this, if given
diff = true                                          # false: the full run only
verdict = { file = "out/spelling.json", key = "summary.passed" }    # see below
```

`name`, `command`, `description` and `doc` are required. `py-qa rule-doc <name>` prints the
check's description, how it runs, and what documents it: a Markdown file whole, a Python file's
module docstring, a shell script's leading comment block. The `docs` lane fails while the `doc`
file is missing or empty. A check is listed by `py-qa rules` and in the agent summary like any
defence, and switched off by removing it.

With `verdict`, the check passes only when it exits 0 and also writes the named JSON file during
this run with the dotted key true: a report that says it failed, or one left by an earlier run,
fails the lane. The test lane takes the same `verdict`, and `diff_verdict` for its
`diff_command`. Identifiers a check prints of its own resolve through `rule_doc_command`, a
command py-qa runs for any identifier nothing else documents, with `{identifier}` as an argument.

`[tool.py-qa.test] setup` lists commands run before the tests, in a full run and a diff run
alike, such as starting a service the tests talk to; one that fails fails the test lane.

## Diff runs

`py-qa run --diff` checks what changed, not the whole project: the commits since the merge base
of the base ref and HEAD, staged and unstaged edits, and files git does not ignore. The base is
`--base <ref>`, else `[tool.py-qa.diff] base`, else the branch `origin/HEAD` names, else the first
of `origin/main`, `origin/master`, `main` and `master` that exists. Each lane narrows:

| Lane                            | In a diff run                                                                                      |
| ------------------------------- | -------------------------------------------------------------------------------------------------- |
| `fmt`, `ruff`, `pylint`         | the changed Python files within the lane's paths                                                   |
| `mypy`                          | its whole scope, since one file's types depend on others; mypy's own cache keeps it quick          |
| `record`, `suppression`, `docs` | the whole project, as in a full run: they are quick, and a stale exception needs the whole picture |
| a project check                 | runs when no `paths` are given or one changed file matches them, as `diff_command` if it has one   |
| `test`                          | the tests the change can affect, with no coverage verdict                                          |

The tests a change can affect come from a graph of the project's files. Every Python file is
parsed for its imports, absolute and relative, and for strings that name a project module (a
`mock.patch` target, an `importlib.import_module` argument) or a project file (by its path, a path
suffix, or a file name no other file shares). A test is selected when a changed file is
reachable from it. Importing a submodule runs its packages' `__init__`, and a test runs every
`conftest.py` above it: a change to that `__init__` or conftest reaches every file that loads it,
but what it imports reaches only the files that import that themselves, which keeps one
package's re-exports from selecting every test. A deleted module selects the tests that still
import it. Parsed results are cached by size and modification time under the git directory, and
files not in the cache are parsed in parallel.

What the graph cannot see is declared in `[tool.py-qa.diff]`:

```toml
[tool.py-qa.diff]
base = "origin/main"
full_tests_on = ["/pyproject.toml", "/uv.lock"]  # the default lists pyproject.toml, the lock files,
                                                 # setup.py, setup.cfg, tox.ini, pytest.ini and more
unmapped = "full"                                # or "ignore"

[[tool.py-qa.diff.map]]
glob = "docs/**/*.md"                            # files a test reads by glob or a computed name
exclude = ["docs/archive/**"]
tests = ["tests/test_docs.py"]                   # [] declares that no test reads them
why = "test_docs reads every page under docs/"
```

A change to a `full_tests_on` file runs the whole test lane. A changed file that is not Python,
that no test reaches and that no map entry matches is unmapped: with `unmapped = "full"`, the
default, it runs the whole test lane too, and either way the run names it. A changed Python file
no test reaches is named as untested. A map entry naming a test that does not exist fails the
test lane. With `[tool.py-qa.test] command`, `diff_command` (with `{tests}`, and `{base}` if
wanted) is what runs the selection; without it the project's command runs whole. Globs here and
in a check's `paths` treat `**` as any number of directories and `*` as part of one; a pattern
with no `/` matches a file name at any depth, and a leading `/` anchors it to the root.

The graph cannot see a module loaded by a name built at run time, and it treats importing a
module as depending on all of it. A diff run is the quick check before committing; the full run
stays the gate, before a merge and in CI.

## Writing rules

Pylint is the host: the [Defence Before Fix register](https://defence-before-fix.github.io/tools/)
grades it green for bespoke rules, and Ruff and mypy cannot host a project's own rule at all.
Write a checker deriving from `pylint.checkers.BaseChecker`, whose `msgs` maps a message id to
its text, a stable symbol, and a description whose first sentence is the standing instruction
(it becomes the rule's line in `py-qa rules` and in the agent summary):

```python
from astroid import nodes
from pylint.checkers import BaseChecker
from pylint.lint import PyLinter

MESSAGES = {
    "W9901": (
        "eval() runs its argument as code (py-qa rule-doc proj-no-eval)",
        "proj-no-eval",
        "Parse input with ast.literal_eval or json.loads, never eval. eval runs whatever text "
        "reaches it.",
    )
}


class NoEvalChecker(BaseChecker):
    name = "proj-no-eval"
    msgs = MESSAGES

    def visit_call(self, node: nodes.Call) -> None:
        if isinstance(node.func, nodes.Name) and node.func.name == "eval":
            self.add_message("proj-no-eval", node=node)


def register(linter: PyLinter) -> None:
    linter.register_checker(NoEvalChecker(linter))
```

List the module under `pylint_plugins` in `[tool.py-qa]`. Every message it defines is then
enabled, listed by `py-qa rules`, and must have a page at `<docs_dir>/<symbol>.md` with the
sections `## What it flags`, `## Why` and `## How to fix correctly`; `py-qa docs-check`
enforces this. Prove it red with the harness on a fixture before trusting a green run
(`py-qa rule proj-no-eval tests/fixtures/eval_used.py`), and keep the fixture test as a
`pylint.testutils.CheckerTestCase` in the project's suite. Use a message id range of your own
(py-qa uses `W97xx`) and keep project symbols out of the `pyqaci-` prefix.

py-qa runs Pylint only as this host: with its own rcfile, `--disable=all`, and the bundled
and project messages enabled. A project that wants one of Pylint's own messages as a defence
names it in `pylint_enable`. General linting is Ruff's job.

### Bundled defences

On in every project, documented offline, and run on py-qa-ci's own source:

| Identifier              | Flags                                                                                           |
| ----------------------- | ----------------------------------------------------------------------------------------------- |
| `pyqaci-sensitive-repr` | a credential-named field printed by the `__repr__` a dataclass or pydantic model generates      |
| `pyqaci-broad-suppress` | `contextlib.suppress(Exception)` or `BaseException`, the context-manager form of `except: pass` |

`py-qa rule-doc <identifier>` prints each page.

## Project record

`qa/record.toml` holds every exception; nothing else can silence a defence:

```toml
[[exception]]
rule = "ruff::S602"                     # <tool>::<identifier as the suppression writes it>
path = "src/deploy/remote.py"           # one file; a configuration setting's path is its file
justification = "The command string is assembled from the three constants in this module and no caller input; the remote host only accepts a shell line."
decided_by = "alice"                    # a person, never automation
decided_on = 2026-01-15                 # UTC date, not in the future
review_by = 2026-04-15                  # within max_review_days of decided_on
```

The suppression itself stays where the tool reads it (`noqa: S602` on the line, an entry in
`per-file-ignores`, `type: ignore[arg-type]`); the record is what makes it legitimate. The
`suppression` lane finds every suppression comment for Ruff, Pylint, mypy, Pyright, Bandit,
Semgrep and coverage.py (`pragma: no cover`), read with `tokenize` so strings never count; every
setting in the Ruff and mypy configuration that silences a finding or excludes a file; a mypy
strictness flag turned off where `strict` or the global section had it on
(`disallow_untyped_defs = false` in an override); and the coverage.py settings that take code
out of measurement (`omit`, `exclude_lines`, `exclude_also`, `partial_branches`). Each must match an exception by
identifier and file. A suppression that names no identifier (a bare `noqa`, `type: ignore`,
`pylint: disable=all`) fails whatever the record says. An exception that covers nothing fails as
stale. `py-qa rule-doc pyqaci.suppression.unrecorded` lists every form, and `py-qa rule-doc`
resolves each route's own identifier too (`py-qa rule-doc mypy::disallow_untyped_defs`). A
record finding points at the line of its `[[exception]]`.

Justifications are checked, not merely required: shorter than 40 characters, or fewer than six
words of their own once stock phrases ("needed for now", "legacy", "TODO", "false positive" and
the rest listed in `py-qa rule-doc pyqaci.record.invalid`) are removed, fails; so does a
justification repeated from another exception. The check cannot tell whether a sentence is true:
that is the Owner's judgement, which is why `py-qa rules` prints every justification together.

The record has a budget (`max_total`, default 20; `max_per_rule`, default 5) and every exception
expires at its `review_by` date.

## Configuration

`[tool.py-qa]` in `pyproject.toml` (optional; unknown keys are rejected). Defaults:

```toml
[tool.py-qa]
record = "qa/record.toml"     # shorthand for [tool.py-qa.record] path
docs_dir = "docs/defences"    # pages for the project's own rules
paths = ["src", "tests"]      # those present; "." when neither is
scan_exclude = []             # globs kept out of the suppression scan and the Pylint pass
pylint_plugins = []           # the project's own Pylint plugin modules
pylint_enable = []            # Pylint's own messages the project adopts as defences
formatter = "ruff"            # or "black", for a project formatted by Black (install it yourself)
lock = true                   # false, or a path: the lock one run at a time holds
# rule_doc_command = ["{python}", "scripts/explain.py", "{identifier}"]  # documents the rest

[tool.py-qa.lane_paths]       # paths of its own for fmt, ruff, mypy or pylint, in place of paths
# mypy = ["src", "scripts"]   # a -p subset is narrowed to the lane's paths; listed by py-qa rules

[tool.py-qa.test]
# command = ["scripts/run_tests.sh"]  # the project's own test entry point, run without a shell,
                                       # in place of pytest under coverage; it owns coverage
# diff_command = ["scripts/run_tests.sh", "{tests}"]  # how a diff run runs its selection
# setup = [["scripts/start-db.sh"]]   # commands run before the tests
# verdict = { file = "out/tests.json", key = "summary.passed" }  # and diff_verdict

# [[tool.py-qa.check]] and [tool.py-qa.diff]: see "Project checks" and "Diff runs"

[tool.py-qa.record]
path = "qa/record.toml"
max_total = 20
max_per_rule = 5
max_review_days = 180

[tool.py-qa.tools]        # explicit -t requests override these switches
fmt = true
record = true
suppression = true
summary = true                # runs only when [tool.py-qa.summary] file is set
docs = true
ruff = true
mypy = true
pylint = true
test = true
coverage = true
audit = false

[tool.py-qa.coverage]
fail_under = 80

[tool.py-qa.summary]
# file = "AGENTS.md"          # the file the project's agents load; unset is off

[tool.py-qa.sensitive_repr]
# names = [...]               # replace the sensitive field-name list
# redacting_types = [...]     # replace the redacting type list
```

**Tool configuration.** A project with its own Ruff configuration (`[tool.ruff]`, `ruff.toml` or
`.ruff.toml`) or mypy configuration (`[tool.mypy]`, `mypy.ini`, `.mypy.ini`, `[mypy]` in
`setup.cfg`) keeps it. Otherwise py-qa passes its bundled one: Ruff with a hazard-focused
rule selection and line length 100, mypy with `strict` and five extra error codes. Both are in
`src/py_qa/defaults/`. A project's own coverage.py configuration decides what is measured;
without one, py-qa measures `paths` other than test directories. A `fail_under` the
project's coverage.py configuration sets is used as it stands; `coverage.fail_under` applies only
where the project has set none.

## Defaults for what the method leaves to the project

| Judgement             | Default                                                                                                                                     |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Where the record is   | `qa/record.toml`, read by every run; `py-qa rules` lists it beside the defences                                                             |
| Where rule pages live | `docs/defences/<identifier>.md`                                                                                                             |
| Sweep scope           | every Python file git does not ignore (or, without git, every `.py` and `.pyi` outside environments and build output), minus `scan_exclude` |
| Fixtures              | beside the project's tests, as `CheckerTestCase` tests or files under `tests/fixtures/`, kept out of the sweep with `scan_exclude`          |
| Hazard                | wrong output produced silently, a crash, an error hidden, or code that cannot be changed safely; style is the formatter's                   |
| Calibrations          | the record budget, the review horizon and the coverage floor above                                                                          |

## Agent summary

With `[tool.py-qa.summary] file` set, `py-qa summary` writes one line per bespoke defence,
phrased as a standing instruction with its documentation route, into a delimited region of that
file, and the `summary` lane fails when the region falls behind the configuration.

## Development

```bash
uv sync
uv run py-qa run
```

CI runs the same command on Python 3.11, 3.12 and 3.13.
