# pyqaci.record.stale

Reported by the `suppression` lane, on a full run only (not with `-p`).

## What it flags

An exception in the project record that matches no suppression: no comment or configuration
setting in its file names its identifier.

## Why

An exception that covers nothing is permission waiting to be used: the next person to add a
suppression for that identifier in that file finds it already approved, for a reason written
about different code.

## How to fix correctly

Delete the exception. If the suppression it covered was moved to another file, move the
exception with it and re-read the justification, since it was written about the old place.
