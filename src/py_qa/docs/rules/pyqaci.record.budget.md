# pyqaci.record.budget

Reported by the `record` lane.

## What it flags

A project record holding more exceptions than `max_total` (default 20), or more exceptions for
one identifier than `max_per_rule` (default 5). Both are set in `[tool.py-qa.record]`.

## Why

Each exception is cheap to add and nobody owns its removal, so records grow until they are
ignored. A budget makes growth a visible decision. An identifier excepted many times is no longer
a set of exceptions but a disagreement with the rule, which is a calibration for the Owner to
make once, openly, rather than one entry at a time.

## How to fix correctly

Fix instances and delete their exceptions until the record is within budget. If the rule itself
is wrong for the project, the Owner changes the configuration that selects it, and that change
is itself recorded as a configuration suppression. Raising `max_total` or `max_per_rule` is the
Owner's decision, made in the same change and visible in review.
