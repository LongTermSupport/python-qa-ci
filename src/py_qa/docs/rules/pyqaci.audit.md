# pyqaci.audit

Reported by the `audit` lane, off by default because it needs network access. Switch it on with
`audit = true` in `[tool.py-qa.tools]` and install the extra: `py-qa-ci[audit]`.

## What it flags

An installed distribution in the running environment with a known vulnerability, as reported by
pip-audit from the Python Packaging Advisory Database.

## Why

A vulnerable dependency is a defect the project did not write and still ships.

## How to fix correctly

Upgrade the named distribution to a fixed version, as pip-audit's output gives it, through the
project's own dependency manager so its lock file records the change. If no fixed version
exists, remove or replace the dependency, or have the Owner accept the risk explicitly in the
project's decision log.
