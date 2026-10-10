# pyqaci.record.invalid

Reported by the `record` lane.

## What it flags

A project record that cannot be parsed, a key other than `[[exception]]`, or an exception that:

- lacks one of `rule`, `path`, `justification`, `decided_by`, `decided_on`, `review_by`, or has
  a key besides them;
- has a `rule` that is not `<tool>::<identifier>`, with tool one of `ruff`, `pylint`, `mypy`,
  `pyright`, `bandit`, `semgrep`;
- has a `path` that is absolute, climbs out with `..`, or is a glob: an exception covers one file;
- has a generic justification (below);
- has a `decided_by` that names automation (`bot`, `ci`, `agent`, a model name);
- has dates that are not TOML dates, a `decided_on` in the future, a `review_by` not after
  `decided_on`, or a `review_by` more than `max_review_days` (default 180) after it;
- has the same justification as an earlier exception.

**The generic check.** A justification fails if it is shorter than 40 characters, or if fewer
than six words remain once these stock phrases are removed: needed for now, for now, will fix
later, fix later, known issue, technical debt, tech debt, false positive, not applicable, same as
above, as above, see above, by design, no reason, won't fix, wontfix, legacy code, legacy, todo,
fixme, temporary, workaround, intentional, required, necessary, ignore, ignored, suppress,
suppressed, n/a. The check cannot tell whether the sentence is true; that is the reviewer's
judgement, which is why `py-qa rules` prints every justification together.

## Why

An exception without a specific reason is indistinguishable from one nobody would defend, and
the person who could tell them apart is usually gone by the time anyone asks. A reason that
could be pasted onto any exception says nothing about this one.

## How to fix correctly

Say what hazard is being accepted and why it cannot happen, or is acceptable, in this file:

```toml
[[exception]]
rule = "mypy::import-untyped"
path = "src/report/pdf.py"
justification = "The PDF library ships no type information; the two calls made here are wrapped in typed helpers in this file and covered by tests/report/test_pdf.py."
decided_by = "alice"
decided_on = 2026-01-15
review_by = 2026-07-01
```
