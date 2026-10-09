# pyqaci-broad-suppress

Pylint message `W9702`, bundled with python-qa and on in every project.

## What it flags

A call that resolves to `contextlib.suppress` with `Exception` or `BaseException` among its
arguments, through any import spelling (`contextlib.suppress`, `from contextlib import suppress as quiet`, `builtins.Exception`). Resolution uses Pylint's inference, so a local class that
happens to be called `Exception` is not flagged, and a function of your own called `suppress` is
not either.

The `except Exception: pass` form of the same hazard is Ruff's `S110` and `BLE001`, which the
bundled Ruff configuration selects; this rule covers the context-manager form they do not see.

## Why

`with contextlib.suppress(Exception):` is `try: ... except Exception: pass` in another shape.
Any failure inside the block, including a typo raising `NameError` or `AttributeError`, is
discarded, and the code after the block runs on a state that was never reached. The defect then
shows up somewhere else, with no trace of where it began.

## How to fix correctly

Name the exceptions the block is expected to raise, and only those:

```python
import contextlib
from pathlib import Path


def remove_if_present(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
```

If a failure really must not stop the program, catch it explicitly and record it, so it is seen:

```python
import logging

logger = logging.getLogger(__name__)


def notify(send) -> None:
    try:
        send()
    except OSError:
        logger.exception("notification failed")
```

## Suppression

Only with `pylint: disable=pyqaci-broad-suppress` on the line, together with a
`pylint::pyqaci-broad-suppress` exception for that file in the project record.
