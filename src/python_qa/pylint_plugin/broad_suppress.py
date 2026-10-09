"""pyqaci-broad-suppress: contextlib.suppress given Exception or BaseException."""

from __future__ import annotations

from astroid import nodes
from astroid.exceptions import InferenceError
from astroid.util import UninferableBase
from pylint.checkers import BaseChecker

MESSAGE = "pyqaci-broad-suppress"
_BROAD = frozenset({"builtins.Exception", "builtins.BaseException"})


class BroadSuppressChecker(BaseChecker):
    """Report contextlib.suppress calls that silence every error in their block."""

    name = "pyqaci-broad-suppress"
    msgs = {
        "W9702": (
            "contextlib.suppress(%s) hides every error raised in its block; name the exceptions "
            "the block expects (python-qa rule-doc pyqaci-broad-suppress)",
            MESSAGE,
            "contextlib.suppress(Exception) is a try/except Exception: pass in another shape: a "
            "failure inside the block disappears and the code after it runs on a state that was "
            "never reached. Suppress only the exceptions the block is expected to raise.",
        )
    }

    def visit_call(self, node: nodes.Call) -> None:
        """Check each argument of a call that resolves to contextlib.suppress."""
        if _qualified_name(node.func) != "contextlib.suppress":
            return
        for argument in node.args:
            if _qualified_name(argument) in _BROAD:
                self.add_message(MESSAGE, node=node, args=(argument.as_string(),))


def _qualified_name(node: nodes.NodeNG) -> str | None:
    try:
        inferred = next(node.infer())
    except (InferenceError, StopIteration):
        return None
    if isinstance(inferred, UninferableBase) or not isinstance(inferred, nodes.ClassDef):
        return None
    return inferred.qname()
