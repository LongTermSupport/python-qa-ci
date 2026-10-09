# pyqaci.summary.stale

Reported by the `summary` lane, when `[tool.python-qa.summary] file` is set.

## What it flags

An agent summary region, in the file named by `file`, that differs from what
`python-qa summary` would generate now, or a file with no region at all.

## Why

The summary is the list of standing instructions an agent loads before it writes code. If it
lags the configuration, the agent is told about rules that are gone and not told about rules that
are now enforced, and learns the difference by violating them.

## How to fix correctly

Run `python-qa summary` and commit the result. The region sits between
`<!-- BEGIN python-qa summary -->` and `<!-- END python-qa summary -->`; edit outside it, never
inside, since it is regenerated.
