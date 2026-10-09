"""The Pylint checkers python-qa bundles; loaded in every project with --load-plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING

from python_qa.pylint_plugin.broad_suppress import BroadSuppressChecker
from python_qa.pylint_plugin.sensitive_repr import SensitiveReprChecker

if TYPE_CHECKING:
    from pylint.lint import PyLinter

CHECKERS = (SensitiveReprChecker, BroadSuppressChecker)
BUNDLED_MESSAGES = tuple(
    definition[1] for checker in CHECKERS for definition in checker.msgs.values()
)


def register(linter: PyLinter) -> None:
    """Register every bundled checker; Pylint calls this for each --load-plugins module."""
    for checker in CHECKERS:
        linter.register_checker(checker(linter))
