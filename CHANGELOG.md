# Changelog

Every release of py-qa-ci, newest first. Versions follow semantic versioning; whilst the major
version is 0, a minor release can break a consuming project, and says how.

## 0.4.0

From switching a large project's whole QA process onto py-qa: about forty checks of its own, a
test suite run under several Pythons, a live service its tests talk to, and a need to check a
change in seconds rather than an hour.

### Added

- **Project checks.** `[[tool.py-qa.check]]` makes a project's own check script a lane: run in
  the detector phase or, with `phase = "runners"`, after the test lane; listed by `py-qa rules`,
  `py-qa tools` and the agent summary; documented by `py-qa rule-doc <name>` from its `doc` file,
  which the `docs` lane requires. `verdict` judges a check by the JSON report it writes as well as
  by its exit status, so a report saying it failed, or one left by an earlier run, fails it.
- **Diff runs.** `py-qa run --diff` (or `--base <ref>`) checks what changed against the merge base
  with a base ref: the format, Ruff and Pylint lanes on the changed Python files, each project
  check when a file it watches changed (`paths`, `diff_command`, `diff = false`), and the test
  lane on the tests the change can affect, read from an import and file-reference graph. What
  the graph cannot see is declared in `[tool.py-qa.diff]` (`full_tests_on`, `unmapped`, and
  `[[tool.py-qa.diff.map]]`), and `[tool.py-qa.diff.selector]` adds a project's own selector's
  tests. py-qa's own inputs (the record, the `docs_dir` pages, the summary file) need no test.
  `py-qa affected` prints the selection and why each test is in it.
- `[tool.py-qa.test] diff_command`, `setup`, `verdict` and `diff_verdict`.
- `rule_doc_command`: a project command that documents identifiers nothing else does.
- `--json <file>`: the outcome of every lane, and a diff run's selection, as JSON.
- `--skip <lane>`: every lane but those named.
- A run lock: a second `py-qa run` in the same work tree exits 3 naming the holder. `lock`
  chooses the file or turns it off; `--no-lock` runs regardless.

### Fixed

- The suppression scan tokenized every Python file, most of a large project's scan on Python
  3.11; a file with no text a directive could start with is now not tokenized (45 s to 4 s on
  2,300 files).
- Black checked with `--diff`, which bypasses Black's cache, so every run re-read every file; it
  now checks with its cache and prints the diff only for a failed check (40 s to 3 s).
- A file named on the command line, as `-p` and a diff run name them, escaped Ruff's and Black's
  exclusions; Ruff now runs with `--force-exclude` and Black with the project's exclusions as
  `--force-exclude`.
- A lane name longer than twelve characters pushed its row out of line in the closing table and
  in `py-qa tools`.
- A command that cannot be started now fails its lane with the shell's status, 127, and says so,
  in place of a traceback.
- A project in a directory below its repository's top was scanned without git, so a file git
  ignores was scanned too; git is now asked whether the directory is in a work tree.

## 0.3.0

From running py-qa-ci as the QA entry point of a large Python project (about 2,300 files, its
own test runner, Black, a narrower mypy scope than its linter's, and inline suppressions with
their reasons beside them).

### May fail a project that passed on 0.2.0

- **mypy strictness turned off is a suppression.** A flag `strict` sets (as the installed mypy
  defines it), a `warn_`, `disallow_` or `strict_` flag, `check_untyped_defs`, `extra_checks` or
  `local_partial_types` set to its loose value where `strict` or the global section had it on,
  and `allow_untyped_globals`, `allow_redefinition`, `allow_empty_bodies` or `implicit_optional`
  switched on, now need an exception (`mypy::disallow_untyped_defs`). This closes the declared
  TOOLING-SPEC 4.3 gap.
- **coverage.py exclusions are suppressions.** `pragma: no cover` and `pragma: no branch`
  comments (`coverage::no-cover`, `coverage::no-branch`), and the `omit`, `exclude_lines`,
  `exclude_also` and `partial_branches` settings, now need an exception: each meets the coverage
  floor by measuring less.

### Added

- `[tool.py-qa.test] command`: the project's own test entry point, run without a shell in place
  of pytest under coverage, for a suite that refuses a bare whole-suite pytest run. It owns
  coverage, so `pyqaci.coverage` is not listed with it.
- `[tool.py-qa.lane_paths]`: paths of its own for `fmt`, `ruff`, `mypy` or `pylint`. A `-p`
  subset is narrowed to them; a lane left with nothing says so. `py-qa rules` lists them.
- The run's closing table shows each lane's seconds and the total.
- `py-qa rule-doc` resolves the route identifiers the suppression lane prints
  (`bandit::B404`, `mypy::disallow_untyped_defs`, `coverage::no-cover`, `ruff::exclude`).
- `py-qa rules --json` carries `paths` and `lane_paths`, and each record entry its `line`.

### Fixed

- Record findings were all reported at line 0 and sorted as text, so exception #18 came before
  #2; they now point at the line of their `[[exception]]`, and a stale exception is reported in
  the record rather than at the file it covers.
- A Ruff setting was reported at the first matching key anywhere in `pyproject.toml`, such as
  `[tool.black]`'s `extend-exclude` or `[tool.deptry]`'s `ignore`; a mypy setting in an
  override at its first mention in the global section. Both are now found in their own table.
- `py-qa tools` printed two arguments of each command (`mypy src`, `pylint --rcfile`); it now
  names the tool and its installed version.
- Pylint ran in one process, most of a large project's run; it now uses a worker per CPU.
- With `FORCE_COLOR` set, Pylint warned that it ignored the text reporter on every run; py-qa now
  asks for the reporter Pylint will use.

## 0.2.0

### Renamed: python-qa-ci is now py-qa-ci

Every name the tool carried is changed. A project upgrading from 0.1.0 changes these:

| What                         | 0.1.0                                                  | 0.2.0                                              |
| ---------------------------- | ------------------------------------------------------ | -------------------------------------------------- |
| Repository                   | `LongTermSupport/python-qa-ci`                         | `LongTermSupport/py-qa-ci`                         |
| Distribution                 | `python-qa-ci`                                         | `py-qa-ci`                                         |
| Command                      | `python-qa`                                            | `py-qa`                                            |
| Import package               | `python_qa`                                            | `py_qa`                                            |
| Bundled Pylint plugin module | `python_qa.pylint_plugin`                              | `py_qa.pylint_plugin`                              |
| Configuration table          | `[tool.python-qa]` and its sub-tables                  | `[tool.py-qa]` and its sub-tables                  |
| Agent summary markers        | `<!-- BEGIN python-qa summary ... -->`, `<!-- END ...` | `<!-- BEGIN py-qa summary ... -->`, `<!-- END ...` |

- **Rule identifiers are unchanged.** They already used the short prefix `pyqaci`, which reads as
  py-qa-ci: `pyqaci.*` for py-qa's own detectors, `pyqaci-sensitive-repr` (W9701) and
  `pyqaci-broad-suppress` (W9702) for the bundled Pylint messages, and the Pylint options
  `--pyqaci-sensitive-names` and `--pyqaci-redacting-types`. Project records, documentation
  pages and anything else that names an identifier need no change.
- **A `[tool.python-qa]` table is now a configuration error** (exit 2), naming the new table.
  Ignoring it would have run every lane on the defaults, without the project's record path,
  plugins or switches.
- **An agent summary region under the former markers** is replaced in place by the next
  `py-qa summary`; until then the `summary` lane reports it stale, as it does after any upgrade.
- GitHub redirects the former repository URL, but a pinned install line should name the new
  one: `py-qa-ci @ git+https://github.com/LongTermSupport/py-qa-ci@v0.2.0`.

## 0.1.0

The first release, as `python-qa-ci`: the `run` pipeline (format, detectors, runners), the
project record, the suppression scan, the bundled Pylint defences `pyqaci-sensitive-repr` and
`pyqaci-broad-suppress`, offline `rule-doc`, `rules`, `docs-check` and the agent summary.
