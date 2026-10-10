# pyqaci.suppression.unrecorded

Reported by the `suppression` lane.

## What it flags

A suppression that names an identifier, with no exception for that identifier and that file in
the project record. The lane reads every Python file in the project (tracked and untracked files
git does not ignore, or every `.py` and `.pyi` file outside environments and build output when
there is no git repository), minus `scan_exclude`, with `tokenize`, so text inside strings and
docstrings is never mistaken for a directive. It recognises:

| Tool    | Comment forms                                                                                                                                                                                     |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ruff    | `noqa: <codes>`, `ruff: noqa: <codes>`, `flake8: noqa: <codes>`, `ruff: ignore[...]`, `ruff: file-ignore[...]`, `ruff: disable[...]`, `isort: skip`, `isort: skip_file`, `isort: off` (as `I001`) |
| Pylint  | `pylint: disable=`, `disable-next=`, `disable-line=`                                                                                                                                              |
| mypy    | `type: ignore[<codes>]`, `mypy: disable-error-code=...`, and any file-level `mypy:` setting that allows, ignores or turns a check off (`allow-untyped-defs`)                                      |
| Pyright | `pyright: ignore[<rules>]`, `pyright: basic`, `pyright: report<Rule>=false` (or `none`, `information`, `warning`)                                                                                 |
| Bandit  | `nosec <codes>`                                                                                                                                                                                   |
| Semgrep | `nosemgrep: <rule ids>`                                                                                                                                                                           |

It also reads the configuration Ruff and mypy load: `ignore`, `extend-ignore`,
`per-file-ignores`, `extend-per-file-ignores`, `exclude` and `extend-exclude` under `[tool.ruff]`,
`[tool.ruff.lint]`, `ruff.toml` and `.ruff.toml`; and `disable_error_code`, `ignore_errors`,
`ignore_missing_imports`, `exclude` and `follow_imports = skip|silent` in `[tool.mypy]`, its
overrides, `mypy.ini`, `.mypy.ini` and the `[mypy]` sections of `setup.cfg`. A setting is
reported at the configuration file, with the identifier `<tool>::<code>` (`ruff::E501`,
`mypy::ignore_errors`, `ruff::exclude`).

## Why

A suppression is a decision to leave a finding unfixed. If it can be written in a comment or a
configuration line that nobody is asked about, the decision is made by whoever typed it, and the
project's Owner never sees it. The project record is the one place such decisions live, with a
reason, a person and a review date, and `py-qa rules` lists them all together.

## How to fix correctly

First, fix the finding and delete the suppression. If it genuinely has to stay, add an exception
to the record (`qa/record.toml` by default) naming the identifier exactly as the suppression
writes it, prefixed with its tool, and the one file it is in:

```toml
[[exception]]
rule = "ruff::S602"
path = "src/deploy/remote.py"
justification = "The command string is assembled from the three constants in this module and no caller input; the remote host only accepts a shell line."
decided_by = "alice"
decided_on = 2026-01-15
review_by = 2026-04-15
```

For a configuration setting, `path` is the configuration file (`pyproject.toml`).
