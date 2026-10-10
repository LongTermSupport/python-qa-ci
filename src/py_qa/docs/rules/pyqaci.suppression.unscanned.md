# pyqaci.suppression.unscanned

Reported by the `suppression` lane.

## What it flags

A Python file the suppression scan could not read: it is not valid UTF-8, or it cannot be
tokenised (an unterminated string, inconsistent indentation).

## Why

A file the scan cannot read is a file whose suppressions are unknown, so a clean result would
claim more than was checked.

## How to fix correctly

Fix the file so it parses; Ruff and mypy will report the same error with its position. If the
file is deliberately not Python (a template, a fixture holding broken code on purpose), keep it
out of the scan with a `scan_exclude` glob in `[tool.py-qa]`; `py-qa rules` lists every
exclusion beside the defences.
