# pyqaci.coverage

Reported by the `coverage` lane, which runs the test suite under coverage.py.

## What it flags

Total coverage below `[tool.python-qa.coverage] fail_under` (default 80), or below the
`fail_under` the project's own coverage.py configuration sets, which then takes precedence so
that python-qa never moves a floor the project chose. When the project has
no coverage.py configuration of its own, python-qa measures its configured `paths` other than
test directories; otherwise coverage.py's own `[tool.coverage]`, `.coveragerc` or `setup.cfg`
settings decide what is measured.

## Why

Code no test executes can change behaviour without any test noticing. A floor stops the tested
share of the code falling silently as code is added.

## How to fix correctly

Read the `Missing` column of the report, and add tests that exercise those lines through the
public behaviour they implement. Lowering `fail_under` is the Owner's decision.
