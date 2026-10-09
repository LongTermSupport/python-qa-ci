# pyqaci.tests

Reported by the `test` lane, a runner. Runners run only once the format and detector phases pass.

## What it flags

A pytest run that does not exit 0: a failing or erroring test, a collection error, or no tests
collected. pytest's own output above the line says which.

## Why

A detector finds a class of defect before the code runs; a test shows one behaviour is right
when it does. The project accepts a change only when both hold.

## How to fix correctly

Read the first failure pytest reports, reproduce it with `python -m pytest <test id>`, and fix
the code or the test, whichever is wrong. When the failure is a defect, follow the Defence
Before Fix method: write the rule that detects its class before fixing it.
