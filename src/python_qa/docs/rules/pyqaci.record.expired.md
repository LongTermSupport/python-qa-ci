# pyqaci.record.expired

Reported by the `record` lane.

## What it flags

An exception whose `review_by` date is before today (UTC).

## Why

The reason for an exception is true when it is written and decays afterwards: a library gains
type information, a caller is removed, the code is rewritten. A review date makes someone look
again, and an expired exception blocks until they do. The friction is the point.

## How to fix correctly

Check whether the suppression is still needed. If not, remove it and the exception. If it is,
re-decide it: update `justification` if the reason has changed, and set a new `decided_on`
(today) and `review_by`, within `max_review_days` of each other.
