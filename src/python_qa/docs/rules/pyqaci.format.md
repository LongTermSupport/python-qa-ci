# pyqaci.format

Reported by the `fmt` lane.

## What it flags

Files `ruff format` would change. Locally the lane formats them in place and passes; with
`--no-fix`, or when the `CI` environment variable is set, it checks instead and prints the diff.

## Why

Formatting changes mixed into a functional change hide the change in review, and a formatter run
by some contributors and not others turns every edit into a reformat of the file. Formatting
first also means every detector after it sees the final text.

## How to fix correctly

Run `python-qa run -t fmt` (or `ruff format`) and commit the result. The project's own
`[tool.ruff.format]` settings apply if it has a Ruff configuration; otherwise the formatter's
defaults do.
