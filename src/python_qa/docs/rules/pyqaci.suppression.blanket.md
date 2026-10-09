# pyqaci.suppression.blanket

Reported by the `suppression` lane.

## What it flags

A suppression that names no identifier, so it silences everything the tool could report there:
a bare `noqa`, `ruff: noqa` or `flake8: noqa` with no codes, `pylint: disable=all`,
`pylint: skip-file`, a bare `type: ignore`, `mypy: ignore-errors`, a bare `pyright: ignore`, a
bare `nosec` and a bare `nosemgrep`. It fails whatever the project record says.

## Why

A blanket suppression cannot be recorded against an identifier, so nobody can say what it was
meant to allow, and it goes on silencing every new finding on that line or in that file,
including ones nobody has seen. It is the widest possible exception with the least information.

## How to fix correctly

Run the tool on the file without the suppression, fix what it reports, and delete the comment.
If one finding really must stay, replace the blanket with the identifier it was hiding and record
that identifier for the file (see `python-qa rule-doc pyqaci.suppression.unrecorded`):

```python
value = parse(raw)  # type: ignore[arg-type]
```
